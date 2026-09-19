"""What a contended receipt insert is allowed to tell the caller.

The receipt is the last write on the governed money path, and it was the only
one without a write-conflict restart: the wallet debit, the permit reserve, the
idempotency record and the dispatch attempt all wrap theirs in
``run_with_write_conflict_retry``. So once those stopped losing SQLite locks,
the surviving contention landed on ``INSERT INTO receipts`` and escaped as an
unclassified JSON-RPC ``internal_error``.

That is the specific thing this file exists to prevent, and the reason it
matters is the one written on ``LedgerWriteContendedError``: a client that
cannot tell an unclassified failure from a named retryable one has to assume
its money may have moved. The case actually observed in CI was a *denial* --
``outcome='denied'``, ``reason_code='permit_budget_exceeded'``,
``credits_charged=0`` -- where nothing had been charged and the true answer was
sitting in the row that failed to insert.

The classification splits the same way the audit chain's does, and for the same
reason (see ``tests/test_audit_chain_contention_surface.py``):

- a refusal that ran nothing may say "retry", because a second attempt costs
  nothing and no terminal record was left behind;
- a call that already ran and was charged may not, because "retry" would invite
  a second execution of something the caller has paid for.

Contention is injected at the receipt service's own session factory rather than
raced. A test that waits for a real lock passes on a fast machine for the wrong
reason -- which is exactly how the original defect survived roughly three weeks
of being called flaky.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.resilience import WRITE_CONFLICT_MAX_ATTEMPTS
from app.db.database import get_session_factory
from app.db.models import ReceiptModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services import receipts as receipts_module
from app.services.receipts import ReceiptWriteContendedError, get_receipt_service
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL_COST = 2.0


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def echo_tool():
    tool_name = "receipt-contention-echo"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name="Receipt contention echo",
        description="Receipt write-contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        yield tool_name, runs
    finally:
        get_service_registry().unregister_local(tool_name)


def _lose_receipt_commits(monkeypatch, *, failures: int | None) -> dict[str, int]:
    """Make the receipt insert's own COMMIT lose write conflicts.

    Patched at the receipts module's ``get_session_factory`` so only the
    receipt write is affected: the permit reserve, the debit and the audit
    append keep the real factory, which keeps each test's failure attributable
    to the write under test.

    ``failures`` is how many COMMITs lose before one is allowed through.
    ``None`` loses every time, which is the only way to reach the exhaustion
    branch without waiting on a real race.
    """
    real_get_session_factory = receipts_module.get_session_factory
    state = {"commits": 0}

    def patched_get_session_factory():
        maker = real_get_session_factory()

        def make_session(*args: Any, **kwargs: Any):
            session = maker(*args, **kwargs)
            real_commit = session.commit

            async def flaky_commit() -> None:
                state["commits"] += 1
                if failures is None or state["commits"] <= failures:
                    # The shape SQLAlchemy raises for SQLITE_BUSY; the shared
                    # classifier matches on the driver text, so the message is
                    # load-bearing, not decoration.
                    raise OperationalError(
                        "INSERT INTO receipts (...) VALUES (...)",
                        {},
                        Exception("database is locked"),
                    )
                await real_commit()

            session.commit = flaky_commit  # type: ignore[method-assign]
            return session

        return make_session

    monkeypatch.setattr(
        receipts_module, "get_session_factory", patched_get_session_factory
    )
    return state


def _call_body(
    *, tool_name: str, wallet_id: str, permit_id: str, idempotency_key: str
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idempotency_key}",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": "hello"},
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


@pytest.mark.anyio
async def test_a_contended_receipt_insert_is_restarted_until_it_lands(
    client: AsyncClient, clean_database: None
) -> None:
    """The write survives lock losses, and leaves exactly one row behind.

    The restart replays a whole transaction, so the thing worth pinning is not
    that it eventually succeeds but that replaying it does not write the
    receipt twice. Every attempt rebuilds its ORM instance from the identity
    fixed before the loop -- same ``receipt_id``, same ``created_at``, same
    signed payload -- so the retries describe one row, not several.
    """
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="receipt-contention-direct",
        idem_key="receipt-contention-permit-0",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_receipt_commits(monkeypatch, failures=5)
        receipt = await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="receipt-contention-direct",
            request_payload={"message": "before"},
            response_payload={"message": "after"},
            ledger_entry_id=None,
            credits_authorized=Decimal("2"),
            credits_charged=Decimal("0"),
            outcome="denied",
            audit_event_id=None,
            reason_code="permit_budget_exceeded",
        )

    assert state["commits"] == 6, state
    assert receipt.outcome == "denied"
    # The denial's real answer survived the contention, which is the whole
    # point: a receipt that reports permit_budget_exceeded is actionable and an
    # internal_error is not.
    assert receipt.reason_code == "permit_budget_exceeded"
    assert receipt.credits_charged == Decimal("0")
    assert await _count_receipts() == 1

    # The row that landed is the one that was signed before the first attempt.
    ok, reason, stored = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert ok, reason
    assert stored is not None
    assert stored.receipt_id == receipt.receipt_id


@pytest.mark.anyio
async def test_a_denial_reports_its_real_reason_through_receipt_contention(
    client: AsyncClient, clean_database: None, echo_tool
) -> None:
    """End to end, the CI failure this fixes: a budget denial over HTTP.

    The permit's cap is below the tool's cost, so the call is refused before
    anything runs and the denial receipt is the only write left to lose. Before
    the restart the caller got ``internal_error`` here; the correct answer,
    ``permit_budget_exceeded``, was sitting in the row that failed to insert.
    """
    tool_name, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=1,  # below TOOL_COST, so the reserve refuses
        idem_key="receipt-contention-permit-1",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_receipt_commits(monkeypatch, failures=5)
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=ctx["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="receipt-contention-denied-1",
            ),
            headers=ctx["agent_headers"],
        )

    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["message"] != "internal_error", error
    assert error["message"] == "permit_budget_exceeded", error
    assert error["code"] == -32003, error
    # A denial that charged nothing still hands back its signed evidence.
    assert error["data"]["receipt"]["outcome"] == "denied", error
    assert runs["count"] == 0


@pytest.mark.anyio
async def test_an_exhausted_denial_receipt_is_named_retryable_not_internal(
    client: AsyncClient, clean_database: None, echo_tool
) -> None:
    """Past the restart budget the loss is still classified, not unclassified.

    Restarting narrows the window; it cannot close it, so the exhaustion branch
    is reachable and is what a caller actually meets on a badly contended box.
    Nothing ran and nothing was charged, and the receipt service proved no row
    is durable before raising, so this earns the same ``-32005`` envelope as a
    lost debit or a busy audit chain -- carrying its own reason, so a client can
    tell the three apart.

    The second half of the test is the obligation that comes with saying
    "retry": the governed idempotency record opened before this denial has to
    be released, or every retry of that key meets ``idempotency_in_progress``
    forever and the -32005 names a retry the caller can never actually make.
    Asserting the code alone passed while that was exactly the case.
    """
    tool_name, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=1,
        idem_key="receipt-contention-permit-2",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_receipt_commits(monkeypatch, failures=None)
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=ctx["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="receipt-contention-denied-2",
            ),
            headers=ctx["agent_headers"],
        )

    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["message"] != "internal_error", error
    assert error["message"] == ReceiptWriteContendedError.reason, error
    assert error["code"] == -32005, error
    # It gave up only after spending the whole documented budget.
    assert state["commits"] == WRITE_CONFLICT_MAX_ATTEMPTS, state
    assert await _count_receipts() == 0
    assert runs["count"] == 0

    # Now take the retry the -32005 promised, on the same key and with the
    # contention gone. It has to reach the real answer.
    again = await client.post(
        "/mcp/messages",
        json=_call_body(
            tool_name=tool_name,
            wallet_id=ctx["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="receipt-contention-denied-2",
        ),
        headers=ctx["agent_headers"],
    )
    assert again.status_code == 200, again.text
    retry_error = again.json()["error"]
    assert retry_error["message"] != "idempotency_in_progress", retry_error
    assert retry_error["message"] == "permit_budget_exceeded", retry_error
    assert await _count_receipts() == 1
    assert runs["count"] == 0


@pytest.mark.anyio
async def test_a_charged_call_is_never_told_to_retry_its_receipt(
    client: AsyncClient, clean_database: None, echo_tool
) -> None:
    """The guard on the classification above.

    Here the permit allows the call, so the tool runs and the wallet is charged
    before the receipt is written. Answering ``-32005`` would invite a second
    execution of something already paid for, and it cannot be softened into a
    success either -- without a receipt there is no terminal outcome to publish
    and reconciliation owns the record from here. So it stays unclassified,
    deliberately, exactly as a post-charge audit-chain loss does.
    """
    tool_name, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=10,
        idem_key="receipt-contention-permit-3",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_receipt_commits(monkeypatch, failures=None)
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=ctx["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="receipt-contention-charged-1",
            ),
            headers=ctx["agent_headers"],
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "error" in body, body
    assert body["error"]["code"] != -32005, body
    assert body["error"]["message"] != ReceiptWriteContendedError.reason, body
    # The hazard the assertion above guards is real: the tool did run.
    assert runs["count"] == 1


@pytest.mark.anyio
async def test_a_refunded_call_that_already_ran_is_never_told_to_retry(
    client: AsyncClient, clean_database: None
) -> None:
    """The second post-effect branch, which the success path does not cover.

    A governed tool that performs its side effect and then raises is refunded
    and its budget released, and the failure is receipted through
    ``_finalize_governed_denial`` rather than the success path -- so that helper
    carries ``effects_committed=True`` at this site and converts its own
    contention. The distinction is easy to lose because the receipt records
    ``credits_charged=0``: the money came back, but the call still ran, and
    ``-32005`` here would invite the side effect a second time.

    It also guards the unwind. The retryable path releases the idempotency
    record to make its own advice true; doing that for this call would free a
    key whose side effect already happened.
    """
    tool_name = "receipt-contention-sideeffect"
    runs = {"count": 0}

    def explode_after_running(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        raise RuntimeError("tool_failed_after_side_effect")

    get_service_registry().register_local(
        service_id=tool_name,
        name="Receipt contention side effect",
        description="Receipt write-contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=explode_after_running,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        ctx = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=ctx["agent_wallet_id"],
            key_id=ctx["key_id"],
            tool_name=tool_name,
            max_credits=10,
            idem_key="receipt-contention-permit-4",
        )
        body = _call_body(
            tool_name=tool_name,
            wallet_id=ctx["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="receipt-contention-refunded-1",
        )

        with pytest.MonkeyPatch.context() as monkeypatch:
            _lose_receipt_commits(monkeypatch, failures=None)
            resp = await client.post(
                "/mcp/messages", json=body, headers=ctx["agent_headers"]
            )

        assert resp.status_code == 200, resp.text
        error = resp.json()["error"]
        assert error["code"] != -32005, error
        assert error["message"] != ReceiptWriteContendedError.reason, error
        assert runs["count"] == 1

        # The key was not freed, so the retry this call was NOT invited to make
        # cannot run the side effect again.
        again = await client.post(
            "/mcp/messages", json=body, headers=ctx["agent_headers"]
        )
        assert again.status_code == 200, again.text
        assert runs["count"] == 1, again.json()
    finally:
        get_service_registry().unregister_local(tool_name)
