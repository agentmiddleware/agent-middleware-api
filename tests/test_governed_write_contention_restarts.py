"""Write-conflict restarts on the three governed-money-path writes that lacked them.

``run_with_write_conflict_retry`` exists because SQLite in WAL mode cannot make
a writer wait once its transaction has read: the read pins a snapshot and the
upgrade returns SQLITE_BUSY_SNAPSHOT without consulting the busy handler. The
only cure is to abandon the snapshot and run the whole transaction again, so a
read-then-write in a single session is the exposed shape and every one of them
on the money path is supposed to be wrapped.

Three were not, and each failed differently:

``IdempotencyService.abandon`` is the one that matters most, because it is what
the contention unwind calls to free the idempotency key after it answers
"retry this key". It runs in the window that just exhausted the receipt
insert's entire restart budget -- the moment it is likeliest to lose -- and its
failure was swallowed by a bare ``except Exception`` + log. So the caller was
told to retry, the record was never deleted, and every retry of that key met
``idempotency_in_progress`` until an operator intervened.
``reconcile_stuck_records`` does not help: it expires only ``upstream_mcp``
rows, and a local tool's uncharged record is excluded there by design.

``BillingEngine.refund_charge`` is called by both governed refund sites from
inside a bare ``except Exception as refund_exc``, so a transient lock was
converted into the terminal claim "the refund failed" -- a signed
``failed_unrefunded`` receipt and a pending reconciliation item for money that
was never actually at risk. The same exception handler covers
``mark_debit_refunded``, where the same lock declared a refund failed that had
already committed.

``McpDispatchAttemptService.complete`` writes the terminal row for a call
already dispatched and charged, so its loss is post-effects and is neither
retryable nor unclassified -- it belongs on ``-32007`` with the receipt and
audit losses that happen on the same side of the boundary.

Contention is injected at each service's own session factory, armed only for
the duration of the method under test, rather than raced. A test that waits on
a real lock passes on a fast machine for the wrong reason.
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
from app.db.models import (
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    ReceiptModel,
)
from app.main import app
from app.routers.mcp import (
    DISPATCH_TERMINAL_CONTENDED_AFTER_EFFECTS,
    TerminalRecordContendedError,
    _dispatch_contention_after_effects,
)
from app.schemas.billing import ServiceCategory
from app.services import idempotency as idempotency_module
from app.services import receipts as receipts_module
from app.services.agent_money import get_agent_money
from app.services.billing_engine import (
    BillingEngine,
    LedgerRefundContendedError,
    LedgerWriteContendedError,
)
from app.services.audit_chain import AuditChainContendedError
from app.services.idempotency import (
    IdempotencyReleaseContendedError,
    IdempotencyService,
    get_idempotency_service,
)
from app.services import mcp_dispatch_attempts as dispatch_module
from app.services.mcp_dispatch_attempts import (
    DISPATCH_CLAIMED,
    DispatchAttemptConflictError,
    DispatchTerminalWriteContendedError,
    McpDispatchAttemptService,
    get_mcp_dispatch_attempt_service,
)
from app.services.receipts import ReceiptWriteContendedError
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
    tool_name = "restart-contention-echo"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name="Restart contention echo",
        description="Write-conflict restart surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        yield tool_name, runs
    finally:
        get_service_registry().unregister_local(tool_name)


def _busy() -> OperationalError:
    """The shape SQLAlchemy raises for SQLITE_BUSY.

    The shared classifier in ``app.core.resilience`` matches on the driver
    text, so the message is load-bearing rather than decoration.
    """
    return OperationalError("UPDATE ... ", {}, Exception("database is locked"))


class _FlakyTransaction:
    """Stands in for ``session.begin()`` so that block's COMMIT can lose.

    ``AsyncSessionTransaction`` defines ``__slots__`` and its ``__aexit__``
    calls the sync transaction's ``__exit__`` directly, so the commit cannot
    be replaced on the object itself. Wrapping the context manager is the
    seam that works: the body runs against the real transaction, and the exit
    -- which is where the COMMIT happens -- is where the conflict is raised.

    The rollback before raising is not decoration. A real lost COMMIT leaves
    the transaction rolled back, and that is precisely why the restart helper
    requires the operation to rebuild its own transaction rather than replay
    anything inside the poisoned one.
    """

    def __init__(self, session: Any, inner: Any, lose: Any) -> None:
        self._session = session
        self._inner = inner
        self._lose = lose

    async def __aenter__(self) -> Any:
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        if exc_type is None and self._lose():
            await self._session.rollback()
            raise _busy()
        return await self._inner.__aexit__(exc_type, exc, tb)


def _lose_commits_during(
    monkeypatch,
    *,
    factory_owner,
    factory_attr: str,
    owner,
    method_name: str,
    failures: int | None,
) -> dict[str, int]:
    """Make one method's COMMITs lose write conflicts, and only that method's.

    Two patches working together. The first replaces the session-factory
    provider -- a module's ``get_session_factory``, or a ``BillingEngine``
    instance's ``_session_factory``; both are callables returning a session
    maker -- with one whose sessions raise SQLITE_BUSY on commit. The second
    wraps ``owner.method_name`` so that provider is armed only while that
    method runs.

    Arming is what keeps the failure attributable. Patching the provider alone
    would break every other write behind it -- ``abandon`` shares its factory
    with ``begin``, ``complete`` and ``mark_charged``, and the billing engine's
    is the same one the debit uses -- and the test would stop being about the
    write under test. Arming also survives the restart loop, which lives
    *inside* the method, so every attempt loses.

    ``failures`` is how many transaction attempts lose before one is allowed
    through; ``None`` loses every time, which is the only way to reach the
    exhaustion branch without waiting on a real race. The returned dict counts
    attempts, so a test can assert the restart actually happened rather than
    that the method merely returned.
    """
    state = {"attempts": 0}
    armed = {"on": False}
    real_provider = getattr(factory_owner, factory_attr)

    def patched_get_session_factory():
        maker = real_provider()

        def make_session(*args: Any, **kwargs: Any):
            session = maker(*args, **kwargs)
            if not armed["on"]:
                return session

            # Decide once per session, not once per commit call. Each restart
            # opens a fresh session, so a session is an attempt -- and
            # ``refund_charge`` ends its ``begin()`` block and then awaits
            # ``session.commit()`` again, so counting commits would report
            # seven attempts for six.
            decided: dict[str, bool] = {}

            def lose() -> bool:
                if "value" not in decided:
                    state["attempts"] += 1
                    decided["value"] = failures is None or state["attempts"] <= failures
                return decided["value"]

            # Two hooks, because the three writes under test commit two
            # different ways. ``abandon`` awaits ``session.commit()``
            # directly; ``refund_charge`` and ``complete`` commit by leaving
            # an ``async with session.begin()`` block, which never touches
            # ``session.commit`` at all -- patching only the first is how an
            # earlier version of this helper reported a restart that had not
            # happened.
            real_commit = session.commit

            async def flaky_commit() -> None:
                if lose():
                    raise _busy()
                await real_commit()

            real_begin = session.begin

            def flaky_begin(*a: Any, **k: Any):
                return _FlakyTransaction(session, real_begin(*a, **k), lose)

            session.commit = flaky_commit  # type: ignore[method-assign]
            session.begin = flaky_begin  # type: ignore[method-assign]
            return session

        return make_session

    monkeypatch.setattr(factory_owner, factory_attr, patched_get_session_factory)

    real_method = getattr(owner, method_name)

    async def armed_method(*args: Any, **kwargs: Any):
        armed["on"] = True
        try:
            return await real_method(*args, **kwargs)
        finally:
            armed["on"] = False

    monkeypatch.setattr(owner, method_name, armed_method)
    return state


def _lose_receipt_commits(monkeypatch, *, failures: int | None) -> dict[str, int]:
    """Make the receipt insert's COMMIT lose, as the receipt surface test does.

    Kept local rather than imported so this file's helpers stay readable side
    by side; the receipt service owns its factory outright, so this one needs
    no arming.
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


async def _count(model) -> int:
    async with get_session_factory()() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _count_records_for(idempotency_key: str) -> int:
    """Rows for one invoke key only.

    Permit creation writes an idempotency record of its own, so a bare count
    over the table would never reach zero and would not be about the record
    under test.
    """
    async with get_session_factory()() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecordModel)
                .where(IdempotencyRecordModel.idempotency_key == idempotency_key)
            )
            or 0
        )


@pytest.mark.anyio
async def test_a_contended_release_still_frees_the_key(
    client: AsyncClient, clean_database: None, echo_tool
) -> None:
    """The case the unwind exists for, with the release itself contended.

    Both writes lose here, which is the realistic pairing rather than a
    contrived one: the unwind only runs because the receipt insert already
    spent its whole restart budget, so the release is attempted in exactly the
    window that just proved to be busy.

    The receipt loss is answered ``-32005 receipt_write_contended``, which
    promises the caller a retry of this key. That promise is only kept if the
    in-progress record is deleted, and before the restart the release's first
    lost COMMIT was swallowed by a bare ``except Exception`` + log -- so the
    retry met ``idempotency_in_progress`` and kept meeting it, because
    ``reconcile_stuck_records`` leaves an uncharged local record alone.

    The assertion that matters is the last one: the retry reaches the real
    answer. Asserting the first response's code alone passed throughout the
    defect.
    """
    tool_name, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=1,
        idem_key="restart-release-permit-1",
    )
    body = _call_body(
        tool_name=tool_name,
        wallet_id=ctx["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="restart-release-key-1",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_receipt_commits(monkeypatch, failures=None)
        release = _lose_commits_during(
            monkeypatch,
            factory_owner=idempotency_module,
            factory_attr="get_session_factory",
            owner=IdempotencyService,
            method_name="abandon",
            failures=5,
        )
        resp = await client.post(
            "/mcp/messages", json=body, headers=ctx["agent_headers"]
        )

    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["code"] == -32005, error
    assert error["message"] == "receipt_write_contended", error
    # The release really was contended and really did restart: six attempts
    # for five losses. Without this the test would pass on an uncontended release.
    assert release["attempts"] == 6, release
    assert runs["count"] == 0

    # The record the -32005 promised to free is gone, so the key is reusable.
    assert await _count_records_for("restart-release-key-1") == 0

    again = await client.post("/mcp/messages", json=body, headers=ctx["agent_headers"])
    assert again.status_code == 200, again.text
    retry_error = again.json()["error"]
    assert retry_error["message"] != "idempotency_in_progress", retry_error
    assert retry_error["message"] == "permit_budget_exceeded", retry_error
    assert await _count(ReceiptModel) == 1
    assert runs["count"] == 0


@pytest.mark.anyio
async def test_an_exhausted_release_is_not_advertised_as_a_retry(
    client: AsyncClient, clean_database: None, echo_tool
) -> None:
    """Restarting narrows the window; it cannot close it.

    When the release spends its whole budget the record is still in progress,
    and re-raising ``receipt_write_contended`` would name a retry of a key that
    will answer ``idempotency_in_progress`` from here on. The caller would be
    told one thing and then meet another, forever.

    So the answer becomes the condition the retry will actually hit. It is
    still ``-32005`` -- nothing ran, nothing was charged, and the row is intact
    for an owner to find -- but it no longer changes its story between the
    first response and the second.
    """
    tool_name, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=1,
        idem_key="restart-release-permit-2",
    )
    body = _call_body(
        tool_name=tool_name,
        wallet_id=ctx["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="restart-release-key-2",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_receipt_commits(monkeypatch, failures=None)
        release = _lose_commits_during(
            monkeypatch,
            factory_owner=idempotency_module,
            factory_attr="get_session_factory",
            owner=IdempotencyService,
            method_name="abandon",
            failures=None,
        )
        resp = await client.post(
            "/mcp/messages", json=body, headers=ctx["agent_headers"]
        )

        assert resp.status_code == 200, resp.text
        error = resp.json()["error"]
        assert error["code"] == -32005, error
        # Not the contention that got us here: that one advertises a retry of
        # a key this request failed to free.
        assert error["message"] != "receipt_write_contended", error
        assert error["message"] == "idempotency_in_progress", error
        # It gave up only after spending the whole documented budget.
        assert release["attempts"] == WRITE_CONFLICT_MAX_ATTEMPTS, release
        assert runs["count"] == 0

    # The record survived, which is what makes the answer above the true one,
    # and the story does not change on the retry.
    assert await _count_records_for("restart-release-key-2") == 1
    again = await client.post("/mcp/messages", json=body, headers=ctx["agent_headers"])
    assert again.status_code == 200, again.text
    assert again.json()["error"]["message"] == "idempotency_in_progress", again.text
    assert runs["count"] == 0


@pytest.mark.anyio
async def test_a_contended_refund_is_restarted_instead_of_declared_failed(
    client: AsyncClient, clean_database: None
) -> None:
    """A transient lock on the refund is not the same fact as "unrefunded".

    Both governed refund sites call ``refund_charge`` inside a bare
    bare exception handler, so without a restart the first lost
    COMMIT was converted into the terminal claim that the refund failed: a
    signed ``failed_unrefunded`` receipt, a pending reconciliation work item,
    and a 500 for the caller -- for money that was only momentarily contended
    and that a second attempt returns immediately.

    The debit this reverses already restarts, so the asymmetry was the whole
    defect: the money could be taken through contention but not given back.
    """
    tool_name = "restart-refund-sideeffect"
    runs = {"count": 0}

    def explode_after_running(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        raise RuntimeError("tool_failed_after_side_effect")

    get_service_registry().register_local(
        service_id=tool_name,
        name="Restart refund side effect",
        description="Write-conflict restart surface test tool",
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
            idem_key="restart-refund-permit-1",
        )
        body = _call_body(
            tool_name=tool_name,
            wallet_id=ctx["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="restart-refund-key-1",
        )

        engine = get_agent_money()._billing_engine
        with pytest.MonkeyPatch.context() as monkeypatch:
            refund = _lose_commits_during(
                monkeypatch,
                factory_owner=engine,
                factory_attr="_session_factory",
                owner=BillingEngine,
                method_name="refund_charge",
                failures=5,
            )
            resp = await client.post(
                "/mcp/messages", json=body, headers=ctx["agent_headers"]
            )

        assert resp.status_code == 200, resp.text
        assert runs["count"] == 1
        assert refund["attempts"] == 6, refund

        error = resp.json()["error"]
        # The tool's own error travels, not infrastructure text about a refund
        # that did in fact land.
        assert "refund_failed" not in error["message"], error
        assert "tool_failed_after_side_effect" in error["message"], error

        # The credit is durable and the receipt says so.
        async with get_session_factory()() as session:
            refunds = (
                (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            LedgerEntryModel.action == "refund"
                        )
                    )
                )
                .scalars()
                .all()
            )
            outcomes = (
                (await session.execute(select(ReceiptModel.outcome))).scalars().all()
            )
        assert len(refunds) == 1, refunds
        assert outcomes == ["failed_refunded"], outcomes
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_an_exhausted_refund_is_named_rather_than_raw_driver_text(
    client: AsyncClient, clean_database: None
) -> None:
    """Past the budget the refund really did not land, and says which failure.

    The callers' terminal handling is already right for this -- a
    ``failed_unrefunded`` receipt and a pending reconciliation item is the
    correct owner for a credit that genuinely did not commit -- so what the
    restart adds past exhaustion is only the reason code. It must not be a
    ``LedgerWriteContendedError``: that type means "nothing moved, retry the
    same key", and the routers answer it with a retryable 409/-32005, which
    for a call that has already run and been charged would invite a second
    execution.
    """
    ctx = await provision_agent_wallet(client)
    money = get_agent_money()
    debit = await money.charge(
        wallet_id=ctx["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
    )

    engine = money._billing_engine
    with pytest.MonkeyPatch.context() as monkeypatch:
        refund = _lose_commits_during(
            monkeypatch,
            factory_owner=engine,
            factory_attr="_session_factory",
            owner=BillingEngine,
            method_name="refund_charge",
            failures=None,
        )
        with pytest.raises(LedgerRefundContendedError) as raised:
            await money.refund_charge(
                wallet_id=ctx["agent_wallet_id"],
                charge_entry_id=debit.entry_id,
            )

    assert refund["attempts"] == WRITE_CONFLICT_MAX_ATTEMPTS, refund
    assert str(raised.value) == LedgerRefundContendedError.reason
    # Not the retryable neighbour, by type and not by convention.
    assert not isinstance(raised.value, LedgerWriteContendedError)
    assert not issubclass(LedgerRefundContendedError, LedgerWriteContendedError)

    # Every attempt rolled back whole: no partial credit, no second credit.
    async with get_session_factory()() as session:
        refunds = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(LedgerEntryModel.action == "refund")
                )
            )
            .scalars()
            .all()
        )
    assert refunds == []


async def _charged_and_claimed_attempt(
    client: AsyncClient, *, suffix: str
) -> tuple[McpDispatchAttemptService, Any]:
    """An attempt in the state ``complete()`` is reached in: sent and paid for.

    Mirrors the router's ordering -- reserve and prepare, debit, attach the
    charge, then take the one-shot send authority -- because the whole point of
    the classification under test is which side of that boundary the write is
    on.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = f"restart-dispatch-{suffix}"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"restart-dispatch-permit-{suffix}",
    )
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/mcp/messages",
        idempotency_key=f"restart-dispatch-key-{suffix}",
        request_payload={"tool": tool_name, "arguments": {"value": suffix}},
        operation_kind="upstream_mcp",
    )
    service = get_mcp_dispatch_attempt_service()
    validation, attempt = await service.authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
        arguments={"value": suffix},
    )
    assert validation.allowed is True
    assert attempt is not None

    debit = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )
    await service.attach_charge(
        attempt_id=attempt.attempt_id,
        ledger_entry_id=debit.entry_id,
        credits_charged=Decimal("1.5"),
    )
    await service.claim_dispatch(attempt.attempt_id)
    return service, attempt


@pytest.mark.anyio
async def test_a_contended_terminal_dispatch_write_is_restarted(
    client: AsyncClient, clean_database: None
) -> None:
    """The next write along from ``attach_charge``, which already restarts.

    ``attach_charge`` carries the note that it is "where write conflicts land
    once the debit itself stops losing them". ``complete()`` is the write
    immediately after it on the same path and had no restart, so the conflicts
    that moved off the debit simply landed one step further along and escaped
    as ``internal_error``.

    Restarting is safe for the reason the replay proves below: a second run
    finds the attempt already terminal and returns it when the terminal fields
    match, so the row is written once no matter how many attempts it takes.
    """
    service, attempt = await _charged_and_claimed_attempt(client, suffix="restart")

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_commits_during(
            monkeypatch,
            factory_owner=dispatch_module,
            factory_attr="get_session_factory",
            owner=McpDispatchAttemptService,
            method_name="complete",
            failures=5,
        )
        terminal = await service.complete(
            attempt_id=attempt.attempt_id,
            state="succeeded",
            result_payload={"message": "ok"},
            error_code=None,
            max_result_bytes=64_000,
        )

    assert state["attempts"] == 6, state
    assert terminal.state == "succeeded"

    async with get_session_factory()() as session:
        stored = await session.get(McpDispatchAttemptModel, attempt.attempt_id)
    assert stored is not None
    assert stored.state == "succeeded"
    assert stored.completed_at is not None


@pytest.mark.anyio
async def test_an_exhausted_terminal_dispatch_write_is_post_effects(
    client: AsyncClient, clean_database: None
) -> None:
    """Past the budget the loss is classified, and classified as non-retryable.

    Every governed caller of ``complete()`` is inside
    ``_execute_upstream_after_charge``, so the call has already been dispatched
    and charged. That fixes the answer: the router re-types this to the same
    ``-32007`` the receipt and audit sites use for their post-effects losses,
    and it must not be reachable by the retryable ``-32005`` handlers or by the
    idempotency unwind, which frees the key.

    The type relationships below are the enforcement -- the ladders select on
    type, so "not a subclass" is the mechanism, not a stylistic preference.
    """
    service, attempt = await _charged_and_claimed_attempt(client, suffix="exhaust")

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_commits_during(
            monkeypatch,
            factory_owner=dispatch_module,
            factory_attr="get_session_factory",
            owner=McpDispatchAttemptService,
            method_name="complete",
            failures=None,
        )
        with pytest.raises(DispatchTerminalWriteContendedError) as raised:
            await service.complete(
                attempt_id=attempt.attempt_id,
                state="succeeded",
                result_payload={"message": "ok"},
                error_code=None,
                max_result_bytes=64_000,
            )

    assert state["attempts"] == WRITE_CONFLICT_MAX_ATTEMPTS, state
    assert str(raised.value) == DispatchTerminalWriteContendedError.reason
    # Not the durable-state conflict: that one means the transition was
    # evaluated and refused, this one means it was never evaluated at all.
    assert not isinstance(raised.value, DispatchAttemptConflictError)

    # The row is untouched, so the dispatch reconciler still owns it.
    async with get_session_factory()() as session:
        stored = await session.get(McpDispatchAttemptModel, attempt.attempt_id)
    assert stored is not None
    assert stored.state == DISPATCH_CLAIMED

    # And the router puts it on the non-retryable side of the boundary.
    converted = _dispatch_contention_after_effects()
    assert isinstance(converted, TerminalRecordContendedError)
    assert converted.reason == DISPATCH_TERMINAL_CONTENDED_AFTER_EFFECTS
    assert converted.jsonrpc_code == -32007
    assert converted.status_code == 500
    # The two handlers that must not be able to catch it, by type.
    assert not isinstance(converted, ReceiptWriteContendedError)
    assert not isinstance(converted, AuditChainContendedError)


@pytest.mark.anyio
async def test_a_contended_refund_checkpoint_does_not_unsay_a_durable_refund(
    client: AsyncClient, clean_database: None
) -> None:
    """The worst variant of the refund defect, and the reason it is fixed here.

    ``mark_debit_refunded`` runs under the same exception handler as the
    refund it records, and that handler turns anything raised into "the refund
    failed". So a lost
    write conflict on the checkpoint declared a refund failed that had already
    committed: the credit is durable in the ledger, only the link recording it
    is missing, and the caller is handed a ``failed_unrefunded`` receipt over
    money that is back in the wallet.

    The restart makes the common case impossible. Past exhaustion the driver
    error is re-raised unchanged, matching ``attach_charge``: the money has
    moved and only the link is missing, so there is no new terminal fact to
    name.
    """
    service, attempt = await _charged_and_claimed_attempt(client, suffix="checkpoint")
    terminal = await service.complete(
        attempt_id=attempt.attempt_id,
        state="returned_error",
        result_payload={"error": "upstream_returned_error"},
        error_code="upstream_returned_error",
        max_result_bytes=64_000,
    )
    assert terminal.ledger_entry_id is not None
    await get_agent_money().refund_charge(
        wallet_id=terminal.wallet_id,
        charge_entry_id=terminal.ledger_entry_id,
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_commits_during(
            monkeypatch,
            factory_owner=dispatch_module,
            factory_attr="get_session_factory",
            owner=McpDispatchAttemptService,
            method_name="mark_debit_refunded",
            failures=5,
        )
        checkpointed = await service.mark_debit_refunded(
            attempt_id=attempt.attempt_id,
            ledger_entry_id=terminal.ledger_entry_id,
        )

    assert state["attempts"] == 6, state
    assert checkpointed.debit_refunded_at is not None

    # The checkpoint agrees with the ledger, which is the whole point: exactly
    # one credit, and a row that admits it landed.
    async with get_session_factory()() as session:
        stored = await session.get(McpDispatchAttemptModel, attempt.attempt_id)
        refunds = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(LedgerEntryModel.action == "refund")
                )
            )
            .scalars()
            .all()
        )
    assert stored is not None
    assert stored.debit_refunded_at is not None
    assert len(refunds) == 1, refunds


@pytest.mark.anyio
async def test_an_exhausted_release_raises_its_own_type_not_a_driver_error(
    client: AsyncClient, clean_database: None
) -> None:
    """The unwind has to tell "not released" from "failed for some reason".

    A generic failure in ``abandon`` stays swallowed and logged, as before --
    the record may well have been someone else's, or already gone. Only the
    exhaustion branch means the specific thing the unwind acts on: this
    request held the row, tried the full budget, and did not free it.
    ``OperationalError`` text cannot carry that distinction, which is why it
    gets a type.
    """
    ctx = await provision_agent_wallet(client)
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=ctx["agent_wallet_id"],
        endpoint="/mcp/messages",
        idempotency_key="restart-release-key-3",
        request_payload={"tool": "anything", "arguments": {}},
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        state = _lose_commits_during(
            monkeypatch,
            factory_owner=idempotency_module,
            factory_attr="get_session_factory",
            owner=IdempotencyService,
            method_name="abandon",
            failures=None,
        )
        with pytest.raises(IdempotencyReleaseContendedError) as raised:
            await get_idempotency_service().abandon(
                wallet_id=ctx["agent_wallet_id"],
                endpoint="/mcp/messages",
                idempotency_key="restart-release-key-3",
                expected_record_id=begun.record_id,
            )

    assert state["attempts"] == WRITE_CONFLICT_MAX_ATTEMPTS, state
    assert str(raised.value) == IdempotencyReleaseContendedError.reason
    # Nothing ran and nothing was charged here, so this is not the
    # post-effects family: a fresh idempotency key is safe after it.
    assert not isinstance(raised.value, TerminalRecordContendedError)
    # And the record really is still there, which is what makes the caller's
    # answer "in progress" rather than "retry this key".
    assert await _count_records_for("restart-release-key-3") == 1


@pytest.mark.anyio
async def test_a_contended_release_is_not_advertised_after_a_lost_debit_either(
    client: AsyncClient, clean_database: None, echo_tool
) -> None:
    """The second unwind, which has the same contract and the same hazard.

    ``except LedgerWriteContendedError`` is a separate handler from the
    receipt/audit unwind, and its own comment states the same dependency: left
    alone, "a caller that follows the documented advice and retries its key
    would get idempotency_in_progress forever". It hands back the permit
    reservation and releases the key for exactly that reason.

    So a contended release there is the same defect in a second place -- the
    -32005 names ``ledger_write_contended`` and invites a retry the record will
    refuse -- and it takes the same answer. The block already raises
    ``IdempotencyInProgressError`` for its two cleanup-failure cases; this is
    the third.
    """
    tool_name, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=10,
        idem_key="restart-release-permit-4",
    )
    body = _call_body(
        tool_name=tool_name,
        wallet_id=ctx["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="restart-release-key-4",
    )

    engine = get_agent_money()._billing_engine
    with pytest.MonkeyPatch.context() as monkeypatch:
        debit = _lose_commits_during(
            monkeypatch,
            factory_owner=engine,
            factory_attr="_session_factory",
            owner=BillingEngine,
            method_name="charge",
            failures=None,
        )
        release = _lose_commits_during(
            monkeypatch,
            factory_owner=idempotency_module,
            factory_attr="get_session_factory",
            owner=IdempotencyService,
            method_name="abandon",
            failures=None,
        )
        resp = await client.post(
            "/mcp/messages", json=body, headers=ctx["agent_headers"]
        )

    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["code"] == -32005, error
    # Not the debit contention: that one advertises a retry of a key this
    # request failed to free.
    assert error["message"] != "ledger_write_contended", error
    assert error["message"] == "idempotency_in_progress", error
    assert debit["attempts"] == WRITE_CONFLICT_MAX_ATTEMPTS, debit
    assert release["attempts"] == WRITE_CONFLICT_MAX_ATTEMPTS, release
    assert runs["count"] == 0

    # Nothing moved, and the record that makes the answer true is still there.
    assert await _count_records_for("restart-release-key-4") == 1
    async with get_session_factory()() as session:
        entries = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(LedgerEntryModel.action == "debit")
                )
            )
            .scalars()
            .all()
        )
    assert entries == []
