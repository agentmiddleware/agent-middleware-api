"""What a contended pending-refund write is allowed to tell the caller.

``RefundReconciliationService.create_pending`` is the last write on the worst
path the gateway has. The tool ran, the caller was charged, and the refund that
should have given the money back already failed. What it writes is the record
of that: a ``failed_unrefunded`` receipt and the durable work item that tells an
operator money is owed, inserted in one transaction so neither can exist without
the other.

It reaches ``ReceiptService.create_receipt`` through the caller-owned branch --
``create_pending`` opens the session and owns the commit -- and that branch is
the one mode of ``create_receipt`` with no write-conflict restart, because
restarting there would replay an insert without replaying the caller's other
work. So the restart has to live out here, around the whole unit, and until it
did a SQLite write conflict at this commit raised a bare ``OperationalError``
that nothing classified. It reached the generic handler as ``internal_error``
and took the entire transaction down with it.

Losing this transaction is not like losing the other post-effects writes. A
contended receipt after a charge leaves the ledger entry and the audit chain to
reconcile from. Here the work item is the only thing that was ever going to tell
anyone that a refund is outstanding, so dropping it silently converts "we owe
this caller money" into no record at all.

Two things therefore have to hold, and this file pins both:

- the write survives contention, and a restart that lands leaves exactly one
  receipt and one work item -- not one per attempt;
- past the restart budget the loss is named, and named *non-retryably*. The
  caller has already paid. ``-32005`` would invite a second execution, and on
  the legacy REST surface a ``409`` would do the same, so the exhausted answer
  is ``-32007`` / HTTP 500 with the after-effects reason.

Contention is injected at the reconciliation session's own transaction rather
than raced, for the reason ``tests/test_receipt_write_contention_surface.py``
gives: a test that waits for a real lock passes on a fast machine for the wrong
reason.
"""

from __future__ import annotations

from decimal import Decimal
import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.resilience import WRITE_CONFLICT_MAX_ATTEMPTS
from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, ReceiptModel
from app.main import app
from app.routers.mcp import RECEIPT_WRITE_CONTENDED_AFTER_EFFECTS
from app.schemas.billing import ServiceCategory
from app.services import refund_reconciliation as reconciliation_module
from app.services.refund_reconciliation import RefundReconciliationContendedError
from app.services.receipts import ReceiptWriteContendedError
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL_COST = 2.0
TOOL_NAME = "refund-contention-tool"


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def standard_mcp_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "false")
    get_settings.cache_clear()


@pytest.fixture
def exploding_tool():
    """A tool that runs, has its effect, and then fails.

    The failure is what sends the call down the refund path, and the run is what
    makes the answer non-retryable: by the time contention is injected the side
    effect has happened and the wallet has moved.
    """
    runs = {"count": 0}

    def explode() -> dict[str, Any]:
        runs["count"] += 1
        raise RuntimeError("tool exploded")

    get_service_registry().register_local(
        service_id=TOOL_NAME,
        name="Refund contention tool",
        description="Refund-reconciliation write-contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=explode,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        yield TOOL_NAME, runs
    finally:
        get_service_registry().unregister_local(TOOL_NAME)


class _ContendedTransaction:
    """Wraps one ``session.begin()`` so its COMMIT loses a write conflict.

    ``AsyncSessionTransaction`` cannot simply have its ``commit`` replaced the
    way ``tests/test_receipt_write_contention_surface.py`` replaces
    ``session.commit``: it declares ``__slots__``, and ``async with`` exits
    through the *sync* transaction's ``__exit__`` rather than calling the async
    ``commit`` at all. So the whole context manager is wrapped instead.

    The real transaction is rolled back before the error is raised, which is
    what a genuine SQLITE_BUSY at COMMIT leaves behind -- without it the next
    attempt would inherit a poisoned session and the restart would be proving
    something easier than the real thing.
    """

    def __init__(self, inner: Any, state: dict[str, int], failures: int | None):
        self._inner = inner
        self._state = state
        self._failures = failures

    async def __aenter__(self) -> Any:
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        if exc_type is not None:
            return await self._inner.__aexit__(exc_type, exc, tb)
        self._state["commits"] += 1
        if self._failures is not None and self._state["commits"] > self._failures:
            return await self._inner.__aexit__(None, None, None)
        # The shape SQLAlchemy raises for SQLITE_BUSY; the shared classifier in
        # app.core.resilience matches on the driver text, so the message is
        # load-bearing rather than decoration.
        lost = OperationalError("COMMIT", {}, Exception("database is locked"))
        await self._inner.__aexit__(type(lost), lost, None)
        raise lost


def _lose_reconciliation_commits(
    monkeypatch, *, failures: int | None
) -> dict[str, int]:
    """Make ``create_pending``'s own transaction lose write conflicts.

    Patched at the reconciliation module's ``get_session_factory`` so only this
    transaction is affected: the charge, the refund attempt and the audit append
    keep the real factory, which keeps each failure attributable to the write
    under test. ``create_pending``'s read-only preflight session opens no
    transaction through ``begin()``, so it is untouched too.

    ``failures`` is how many COMMITs lose before one is allowed through.
    ``None`` loses every time, which is the only way to reach the exhaustion
    branch without waiting on a real race.
    """
    real_get_session_factory = reconciliation_module.get_session_factory
    state = {"commits": 0}

    def patched_get_session_factory():
        maker = real_get_session_factory()

        def make_session(*args: Any, **kwargs: Any):
            session = maker(*args, **kwargs)
            real_begin = session.begin

            def flaky_begin(*a: Any, **k: Any):
                return _ContendedTransaction(real_begin(*a, **k), state, failures)

            session.begin = flaky_begin  # type: ignore[method-assign]
            return session

        return make_session

    monkeypatch.setattr(
        reconciliation_module, "get_session_factory", patched_get_session_factory
    )
    return state


async def _failing_refund(self, **_kwargs):  # noqa: ANN001
    raise RuntimeError("refund down")


async def _setup(client: AsyncClient, *, idem_suffix: str) -> dict[str, Any]:
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=TOOL_NAME,
        max_credits=10,
        idem_key=f"refund-contention-permit-{idem_suffix}",
    )
    return {"ctx": provisioned, "permit": permit}


def _call_body(
    *, wallet_id: str, permit_id: str, idempotency_key: str
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idempotency_key}",
        "method": "tools/call",
        "params": {
            "name": TOOL_NAME,
            "arguments": {},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


async def _count_receipts() -> int:
    async with get_session_factory()() as session:
        return int(
            await session.scalar(select(func.count()).select_from(ReceiptModel)) or 0
        )


async def _work_items() -> list[dict[str, Any]]:
    """Every durable pending-refund work item currently recorded."""
    async with get_session_factory()() as session:
        records = (
            (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.response_json.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    items = []
    for record in records:
        payload = json.loads(record.response_json or "{}")
        item = payload.get("refund_reconciliation")
        if isinstance(item, dict):
            items.append(item)
    return items


@pytest.mark.anyio
async def test_a_contended_pending_refund_is_restarted_until_it_lands(
    client: AsyncClient, clean_database: None, exploding_tool
) -> None:
    """The write survives lock losses, and leaves one receipt and one work item.

    The restart replays a whole transaction -- the locked checkpoint read, the
    signed receipt and the work item are all rebuilt per attempt -- so the thing
    worth pinning is not that it eventually succeeds but that replaying it does
    not write the evidence twice. Two receipts for one charge would be worse
    than none: the operator queue would show a debt owed twice over.

    The attempt count is asserted because without it this test passes just as
    well against a version that never restarts at all.
    """
    _tool_name, runs = exploding_tool
    case = await _setup(client, idem_suffix="lands")
    ctx = case["ctx"]
    body = _call_body(
        wallet_id=ctx["agent_wallet_id"],
        permit_id=case["permit"]["permit_id"],
        idempotency_key="refund-contention-lands",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_reconciliation_commits(monkeypatch, failures=5)
        with patch(
            "app.services.agent_money.AgentMoney.refund_charge", _failing_refund
        ):
            resp = await client.post(
                "/mcp/messages", json=body, headers=ctx["agent_headers"]
            )

    # Six commits: five lost, the sixth landed.
    assert state["commits"] == 6, state
    assert resp.status_code == 200, resp.text
    data = resp.json()["error"]["data"]
    assert data["receipt"]["outcome"] == "failed_unrefunded", data
    assert Decimal(data["receipt"]["credits_charged"]) == Decimal("2"), data
    assert data["refund_reconciliation"]["status"] == "pending", data

    # The two halves of the evidence are both durable, and there is exactly one
    # of each -- the restarts describe one debt, not six.
    assert await _count_receipts() == 1
    items = await _work_items()
    assert len(items) == 1, items
    assert items[0]["status"] == "pending", items[0]
    assert items[0]["receipt_id"] == data["receipt"]["receipt_id"], items[0]
    assert Decimal(items[0]["credits"]) == Decimal("2"), items[0]
    # The hazard the restart protects is real: the tool did run, once.
    assert runs["count"] == 1


@pytest.mark.anyio
async def test_an_exhausted_pending_refund_is_named_terminal_not_internal(
    client: AsyncClient, clean_database: None, exploding_tool
) -> None:
    """Past the restart budget the loss is classified, and non-retryably.

    This is the state the whole file exists for: the tool ran, the caller was
    charged, the refund failed, and now even the record of that failure is gone.
    ``internal_error`` was the old answer and it is the wrong one twice over --
    ``-32603`` is this pipeline's *unclassified* channel, and a client reading
    "internal error" as "try again" would run and pay for the call a second
    time with a fresh key.

    ``-32005`` is asserted against explicitly rather than implied by the
    ``-32007`` check, because ``-32005`` is the specific wrong answer the
    neighbouring ``ReceiptWriteContendedError`` would have produced had this
    path reused it.
    """
    _tool_name, runs = exploding_tool
    case = await _setup(client, idem_suffix="exhausted")
    ctx = case["ctx"]
    body = _call_body(
        wallet_id=ctx["agent_wallet_id"],
        permit_id=case["permit"]["permit_id"],
        idempotency_key="refund-contention-exhausted",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_reconciliation_commits(monkeypatch, failures=None)
        with patch(
            "app.services.agent_money.AgentMoney.refund_charge", _failing_refund
        ):
            resp = await client.post(
                "/mcp/messages", json=body, headers=ctx["agent_headers"]
            )

    # It gave up only after spending the whole documented budget.
    assert state["commits"] == WRITE_CONFLICT_MAX_ATTEMPTS, state
    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["code"] != -32005, error
    assert error["code"] != -32603, error
    assert error["message"] != ReceiptWriteContendedError.reason, error
    assert error["message"] != RefundReconciliationContendedError.reason, error
    assert error["code"] == -32007, error
    assert error["message"] == RECEIPT_WRITE_CONTENDED_AFTER_EFFECTS, error
    data = error["data"]
    assert data["error"] == "manual_review_required", data
    assert data["reason_code"] == RECEIPT_WRITE_CONTENDED_AFTER_EFFECTS, data
    assert data["remediation"]["type"] == "reconcile_out_of_band", data

    # Nothing is durable, which is what makes the answer honest rather than a
    # half-written debt: the transaction rolled back whole every time.
    assert await _count_receipts() == 0
    assert await _work_items() == []
    assert runs["count"] == 1


@pytest.mark.anyio
async def test_the_exhausted_pending_refund_never_frees_the_charged_key(
    client: AsyncClient, clean_database: None, exploding_tool
) -> None:
    """The guard on the classification above, and the reason for the new type.

    ``_execute_registered_tool``'s unwind abandons the in-progress idempotency
    record when it sees the retryable contention types, which is correct for a
    loss before any effects and catastrophic here: freeing this key would let
    the caller's retry run and charge a call they have already paid for.

    ``TerminalRecordContendedError`` is deliberately not one of those types, so
    the record stays held and a retry of the same key meets the invocation that
    ran rather than executing again. That is the property worth a test, because
    it is invisible in the error body and would be silently lost by re-typing
    this path onto ``ReceiptWriteContendedError``.
    """
    _tool_name, runs = exploding_tool
    case = await _setup(client, idem_suffix="held")
    ctx = case["ctx"]
    body = _call_body(
        wallet_id=ctx["agent_wallet_id"],
        permit_id=case["permit"]["permit_id"],
        idempotency_key="refund-contention-held",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_reconciliation_commits(monkeypatch, failures=None)
        with patch(
            "app.services.agent_money.AgentMoney.refund_charge", _failing_refund
        ):
            resp = await client.post(
                "/mcp/messages", json=body, headers=ctx["agent_headers"]
            )
    assert resp.json()["error"]["code"] == -32007, resp.text
    assert runs["count"] == 1

    # The retry the caller was NOT invited to make cannot run the tool again.
    again = await client.post("/mcp/messages", json=body, headers=ctx["agent_headers"])
    assert again.status_code == 200, again.text
    assert runs["count"] == 1, again.json()


@pytest.mark.anyio
async def test_the_standard_surface_answers_the_same_named_outcome(
    client: AsyncClient, clean_database: None, standard_mcp_enabled, exploding_tool
) -> None:
    """``/mcp`` classifies in its own handler, so the name has to reach it too.

    The two JSON-RPC transports do not share an exception ladder: ``/mcp``
    mints its own permit and maps typed errors into ``McpError`` itself. This
    path reaches that ladder only because ``_finalize_unrefunded_failure``
    re-types the loss before it leaves the router helper, so the assertion here
    is really that the single re-type covers a surface it never mentions.
    """
    _tool_name, runs = exploding_tool
    ctx = (await _setup(client, idem_suffix="standard"))["ctx"]

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_reconciliation_commits(monkeypatch, failures=None)
        with patch(
            "app.services.agent_money.AgentMoney.refund_charge", _failing_refund
        ):
            resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {"name": TOOL_NAME, "arguments": {}},
                },
                headers={
                    **ctx["agent_headers"],
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "Idempotency-Key": "refund-contention-standard",
                },
            )

    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["code"] != -32005, error
    assert error["code"] == -32007, error
    assert error["message"] == RECEIPT_WRITE_CONTENDED_AFTER_EFFECTS, error
    data = error["data"]
    assert data["error"] == "manual_review_required", data
    assert data["reason_code"] == RECEIPT_WRITE_CONTENDED_AFTER_EFFECTS, data
    assert data["remediation"]["type"] == "reconcile_out_of_band", data
    assert runs["count"] == 1
    assert await _count_receipts() == 0
    assert await _work_items() == []


@pytest.mark.anyio
async def test_the_legacy_rest_surface_names_the_exhausted_pending_refund(
    client: AsyncClient, clean_database: None, exploding_tool
) -> None:
    """``/mcp/tools/{id}/invoke`` has its own ladder, and its own way to hide.

    That ladder ends in ``except Exception`` returning a 200 carrying
    ``isError`` and an opaque ``internal_error``, so an unclassified loss does
    not fail loudly anywhere on this transport -- it just stops being
    distinguishable from a bug. Asserting the status code is what excludes that
    fallthrough: the internal_error answer is a 200.

    The 409 is asserted against for the opposite reason. This surface answers
    the retryable contention family with 409, and a 409 here would be the
    legacy-transport spelling of "run your paid call again".
    """
    _tool_name, runs = exploding_tool
    case = await _setup(client, idem_suffix="rest")
    ctx = case["ctx"]
    body = {
        "name": TOOL_NAME,
        "arguments": {},
        "mcp_context": {
            "wallet_id": ctx["agent_wallet_id"],
            "permit_id": case["permit"]["permit_id"],
            "idempotency_key": "refund-contention-rest",
        },
    }

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_reconciliation_commits(monkeypatch, failures=None)
        with patch(
            "app.services.agent_money.AgentMoney.refund_charge", _failing_refund
        ):
            resp = await client.post(
                f"/mcp/tools/{TOOL_NAME}/invoke",
                json=body,
                headers=ctx["agent_headers"],
            )

    assert resp.status_code != 200, resp.text
    assert resp.status_code != 409, resp.text
    assert resp.status_code == 500, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "manual_review_required", detail
    assert detail["reason_code"] == RECEIPT_WRITE_CONTENDED_AFTER_EFFECTS, detail
    assert detail["remediation"]["type"] == "reconcile_out_of_band", detail
    assert runs["count"] == 1
    assert await _count_receipts() == 0
    assert await _work_items() == []
