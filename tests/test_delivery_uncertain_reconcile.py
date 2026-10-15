"""delivery_uncertain reconciliation: leasing, quiescence, the 404 rule, refunds.

Pins:
- the status probe in ``app.services.upstream_mcp``: only an identifier-bound
  HTTP 200 attestation resolves; a 404 is unknown even with a body claiming
  not-executed; the operator bearer is sent and never stored on the row;
- leasing commits before network I/O, uses FOR UPDATE SKIP LOCKED on
  PostgreSQL, and a lost lease resolves nothing;
- a not-executed answer before quiescence moves nothing;
- with the refund policy on, a post-quiescence attestation refunds the debit
  and releases the reservation exactly once, crash-resumably, and the signed
  delivery_uncertain receipt still verifies unchanged;
- tools without a status endpoint stay in manual review.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.core.time import to_naive_utc
from app.db.database import get_session_factory
from app.db.models import (
    ControlPlaneAuditEventModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    ReceiptModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.mcp_dispatch_attempts import (
    DispatchAttemptConflictError,
    get_mcp_dispatch_attempt_service,
)
from app.services.permits import PermitError, get_permit_service
from app.services.receipts import get_receipt_service
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import (
    UpstreamMcpConfiguration,
    UpstreamMcpConfigurationError,
    UpstreamMcpStatusProbe,
    UpstreamStatusOutcome,
    UpstreamStatusProbeError,
)
from app.services.upstream_reconcile import (
    DeliveryUncertainReconcileWorker,
    ParkedCall,
    ProviderLookup,
    ProviderOutcome,
    UpstreamStatusEndpointProbe,
    build_configured_probe,
    quiescence_allowance_seconds,
    resolution_event_id,
)
from tests.test_upstream_reconcile_worker import (
    TEST_ORIGIN,
    ScriptedExecutor,
    _invoke,
    _parked_attempt,
)

TOKEN = "status-probe-secret-token"
STATUS_URL = "https://partner.example.com/agent-middleware/status"
QUIESCENCE = 600


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@dataclass
class ScriptedProbe:
    public_tool_id: str
    outcome: ProviderOutcome = ProviderOutcome.NOT_EXECUTED
    upstream_origin: str = TEST_ORIGIN
    on_lookup: Callable[[ParkedCall], Any] | None = None
    seen: list[ParkedCall] = field(default_factory=list)

    async def lookup(self, call: ParkedCall) -> ProviderLookup:
        self.seen.append(call)
        if self.on_lookup is not None:
            await self.on_lookup(call)
        return ProviderLookup(self.outcome, "prov-1")


@dataclass
class Parked:
    tool: str
    executor: ScriptedExecutor
    wallet_id: str
    permit_id: str
    idem_key: str
    headers: dict[str, str]
    receipt: dict[str, Any]
    attempt: McpDispatchAttemptModel

    @property
    def dispatched(self) -> datetime:
        return to_naive_utc(self.attempt.dispatched_at or self.attempt.completed_at)


async def _park(client: AsyncClient, tool: str, idem_key: str) -> Parked:
    executor = ScriptedExecutor(mode="uncertain")
    result = await _invoke(client, executor, tool_name=tool, idem_key=idem_key)
    receipt = result["body"]["error"]["data"]["receipt"]
    assert receipt["outcome"] == "delivery_uncertain"
    attempt = await _parked_attempt(result["wallet_id"])
    return Parked(
        tool=tool,
        executor=executor,
        wallet_id=result["wallet_id"],
        permit_id=result["permit_id"],
        idem_key=idem_key,
        headers=result["headers"],
        receipt=receipt,
        attempt=attempt,
    )


def _worker(
    probe: Any,
    clock: dict[str, datetime],
    *,
    refund: bool = True,
    **overrides: Any,
) -> DeliveryUncertainReconcileWorker:
    options: dict[str, Any] = {
        "backoff_seconds": [1],
        "alert_age_seconds": 10**6,
        "lease_seconds": 60,
        "quiescence_seconds": QUIESCENCE,
        "refund_on_attested_not_executed": refund,
        "now": lambda: clock["now"],
    }
    options.update(overrides)
    return DeliveryUncertainReconcileWorker(probe, **options)


async def _money_snapshot(wallet_id: str, permit_id: str) -> tuple[Decimal, Decimal]:
    """Exact stored balance and permit spend (the wallet API rounds to float)."""
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, wallet_id)
        permit = await session.get(PermitModel, permit_id)
        assert wallet is not None and permit is not None
        return wallet.balance, permit.spent_credits


async def _attempt(attempt_id: str) -> McpDispatchAttemptModel:
    async with get_session_factory()() as session:
        row = await session.get(McpDispatchAttemptModel, attempt_id)
        assert row is not None
        return row


async def _refunds(charge_entry_id: str) -> list[LedgerEntryModel]:
    async with get_session_factory()() as session:
        return list(
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.correlation_id == charge_entry_id,
                        LedgerEntryModel.action == "refund",
                    )
                )
            ).scalars()
        )


async def _receipt_row(receipt_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        row = await session.get(ReceiptModel, receipt_id)
        assert row is not None
        return row.model_dump()


async def _replay(client: AsyncClient, parked: Parked) -> dict[str, Any]:
    """Same-key replay through the registry the call was made with."""
    get_service_registry().register_upstream(
        service_id=parked.tool,
        name="Reconcile Worker Test Tool",
        description="Test tool",
        category=ServiceCategory.AGENT_COMMS,
        executor=parked.executor,
        input_schema={"type": "object", "properties": {"test": {"type": "string"}}},
        output_schema=None,
        credits_per_unit=2.0,
        upstream_tool_name=parked.tool,
        upstream_origin=TEST_ORIGIN,
    )
    try:
        response = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": parked.tool,
                    "arguments": {"test": "value"},
                    "mcpContext": {
                        "wallet_id": parked.wallet_id,
                        "permit_id": parked.permit_id,
                        "idempotency_key": parked.idem_key,
                    },
                },
            },
            headers=parked.headers,
        )
    finally:
        get_service_registry().unregister_local(parked.tool)
    return response.json()


# --- quiescence + refund ---------------------------------------------------


@pytest.mark.anyio
async def test_not_executed_before_quiescence_moves_nothing_then_refunds_once(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-quiescence"
    try:
        parked = await _park(client, tool, "rq-1")
    finally:
        get_service_registry().unregister_local(tool)
    before = await _money_snapshot(parked.wallet_id, parked.permit_id)
    receipt_before = await _receipt_row(parked.receipt["receipt_id"])
    charge = parked.attempt.ledger_entry_id
    assert charge is not None

    clock = {"now": parked.dispatched + timedelta(seconds=QUIESCENCE // 2)}
    probe = ScriptedProbe(tool, ProviderOutcome.NOT_EXECUTED)

    # Inside the window: an early "not executed" may be "not yet visible".
    sweep = await _worker(probe, clock).run_once()
    assert (sweep.probed, sweep.deferred_quiescence, sweep.refunded) == (1, 1, 0)
    assert await _money_snapshot(parked.wallet_id, parked.permit_id) == before
    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status is None
    deadline = parked.dispatched + timedelta(seconds=QUIESCENCE)
    assert to_naive_utc(row.reconcile_next_probe_at) > deadline
    assert await _refunds(charge) == []

    # Exactly at the boundary is still inside the window (strictly greater).
    clock["now"] = deadline
    assert (await _worker(probe, clock).run_once()).probed == 0

    # Past quiescence: refund + release, exactly once.
    clock["now"] = deadline + timedelta(seconds=2)
    sweep = await _worker(probe, clock).run_once()
    assert (sweep.refunded, sweep.resolved_not_executed) == (1, 1)

    balance_before, spent_before = before
    balance_after, spent_after = await _money_snapshot(
        parked.wallet_id, parked.permit_id
    )
    assert balance_after == balance_before + Decimal("2")
    assert spent_after == spent_before - Decimal("2")
    refunds = await _refunds(charge)
    assert [r.entry_id for r in refunds] == [f"refund-{charge}"]

    row = await _attempt(parked.attempt.attempt_id)
    assert row.state == "delivery_uncertain"  # state is never rewritten
    assert row.reconcile_status == "not_executed_refunded"
    assert row.debit_refunded_at is not None
    assert row.budget_released_at is not None
    assert row.reconcile_lease_owner is None
    assert row.credits_charged == Decimal("2")  # the receipt's claim is history

    # Signed evidence of the resolution, bound to the receipt.
    async with get_session_factory()() as session:
        event = await session.get(
            ControlPlaneAuditEventModel, resolution_event_id(row.attempt_id)
        )
        assert event is not None and event.signature
        metadata = json.loads(event.metadata_json or "{}")
    assert metadata["budget_action"] == "refunded"
    assert metadata["refund_ledger_entry_id"] == f"refund-{charge}"
    assert metadata["receipt_id"] == parked.receipt["receipt_id"]

    # The receipt is untouched and still verifies.
    assert await _receipt_row(parked.receipt["receipt_id"]) == receipt_before
    valid, reason, _ = await get_receipt_service().verify_receipt(
        parked.receipt["receipt_id"]
    )
    assert valid, reason

    # Charge-once: more sweeps, fresh workers, and the once-only gates
    # themselves cannot refund or release a second time.
    clock["now"] += timedelta(hours=1)
    assert (await _worker(probe, clock).run_once()).refunded == 0
    # The status is terminal now, so the release gate refuses outright.
    with pytest.raises(PermitError):
        await get_permit_service().release_dispatch_budget_once(
            row.attempt_id, is_system=True
        )
    await get_agent_money().refund_charge(
        wallet_id=parked.wallet_id, charge_entry_id=charge
    )
    assert len(await _refunds(charge)) == 1
    assert await _money_snapshot(parked.wallet_id, parked.permit_id) == (
        balance_after,
        spent_after,
    )
    assert len(probe.seen) == 2  # one deferred, one decisive; never again


@pytest.mark.anyio
async def test_refund_policy_off_leaves_debit_standing(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-policy-off"
    try:
        parked = await _park(client, tool, "rp-1")
    finally:
        get_service_registry().unregister_local(tool)
    before = await _money_snapshot(parked.wallet_id, parked.permit_id)
    clock = {"now": parked.dispatched + timedelta(seconds=QUIESCENCE + 5)}
    sweep = await _worker(
        ScriptedProbe(tool, ProviderOutcome.NOT_EXECUTED), clock, refund=False
    ).run_once()
    assert (sweep.resolved_not_executed, sweep.refunded) == (1, 0)
    assert await _money_snapshot(parked.wallet_id, parked.permit_id) == before
    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status == "not_executed_review"
    assert row.debit_refunded_at is None and row.budget_released_at is None


@pytest.mark.anyio
async def test_replay_after_refund_never_redispatches(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-replay"
    try:
        parked = await _park(client, tool, "rr-1")
    finally:
        get_service_registry().unregister_local(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=QUIESCENCE + 5)}
    assert (await _worker(ScriptedProbe(tool), clock).run_once()).refunded == 1
    assert len(parked.executor.forwarded_keys) == 1

    body = await _replay(client, parked)
    assert len(parked.executor.forwarded_keys) == 1  # no second dispatch
    assert (
        body["error"]["data"]["receipt"]["receipt_id"] == (parked.receipt["receipt_id"])
    )


@pytest.mark.anyio
async def test_crash_mid_refund_resumes_from_durable_decision(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-crash-resume"
    try:
        parked = await _park(client, tool, "rc-1")
    finally:
        get_service_registry().unregister_local(tool)
    before = await _money_snapshot(parked.wallet_id, parked.permit_id)
    charge = parked.attempt.ledger_entry_id
    assert charge is not None

    class DyingPermits:
        """Refund lands, then the process dies before the budget release."""

        async def release_dispatch_budget_once(self, *args: Any, **kw: Any) -> bool:
            raise RuntimeError("process died")

    probe = ScriptedProbe(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=QUIESCENCE + 5)}
    sweep = await _worker(probe, clock, permit_service=DyingPermits()).run_once()  # type: ignore[arg-type]
    assert sweep.refunded == 0
    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status == "not_executed_refund_pending"
    assert row.debit_refunded_at is not None and row.budget_released_at is None
    # Half-applied: the refund counts, the reservation is still held, and a
    # budget rebuild still treats the receipt as consumed so the pending
    # release cannot subtract the same credits twice.
    async with get_session_factory()() as session:
        consumed = await get_permit_service()._consumed_credits(
            session, parked.permit_id
        )
    assert consumed == Decimal("2")

    # Lease still held: an immediate sweep does not touch it.
    assert (await _worker(probe, clock).run_once()).refunded == 0
    # After lease expiry a fresh worker finishes without asking again.
    clock["now"] += timedelta(seconds=61)
    sweep = await _worker(probe, clock).run_once()
    assert (sweep.refunded, sweep.probed) == (1, 0)
    assert len(probe.seen) == 1
    assert len(await _refunds(charge)) == 1
    balance_before, spent_before = before
    assert await _money_snapshot(parked.wallet_id, parked.permit_id) == (
        balance_before + Decimal("2"),
        spent_before - Decimal("2"),
    )
    async with get_session_factory()() as session:
        consumed = await get_permit_service()._consumed_credits(
            session, parked.permit_id
        )
    assert consumed == Decimal("0")


@pytest.mark.anyio
async def test_audit_written_after_resolution_commit_is_repaired(
    client: AsyncClient, clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = "reconcile-audit-repair"
    try:
        parked = await _park(client, tool, "ra-1")
    finally:
        get_service_registry().unregister_local(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=5)}
    worker = _worker(ScriptedProbe(tool, ProviderOutcome.EXECUTED), clock)

    original = DeliveryUncertainReconcileWorker._record_resolution

    async def die(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("process died after commit")

    monkeypatch.setattr(DeliveryUncertainReconcileWorker, "_record_resolution", die)
    with pytest.raises(RuntimeError):
        await worker.run_once()
    monkeypatch.setattr(
        DeliveryUncertainReconcileWorker, "_record_resolution", original
    )
    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status == "executed"
    event_id = resolution_event_id(row.attempt_id)
    async with get_session_factory()() as session:
        assert await session.get(ControlPlaneAuditEventModel, event_id) is None

    assert (await worker.run_once()).audits_repaired == 1
    async with get_session_factory()() as session:
        event = await session.get(ControlPlaneAuditEventModel, event_id)
        assert event is not None
        assert json.loads(event.metadata_json or "{}")["repaired"] is True
    assert (await worker.run_once()).audits_repaired == 0


# --- leasing ---------------------------------------------------------------


def test_claim_uses_for_update_skip_locked_on_postgres() -> None:
    worker = DeliveryUncertainReconcileWorker(
        ScriptedProbe("t"), quiescence_seconds=0, backoff_seconds=[1]
    )
    sql = str(
        worker.claim_statement(datetime(2026, 1, 1)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "FOR UPDATE OF mcp_dispatch_attempts SKIP LOCKED" in sql


@pytest.mark.anyio
async def test_lease_is_committed_before_network_io(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-lease-visible"
    try:
        parked = await _park(client, tool, "rl-1")
    finally:
        get_service_registry().unregister_local(tool)
    observed: dict[str, Any] = {}

    async def during_probe(call: ParkedCall) -> None:
        # A separate session sees the lease (so it was committed) and can
        # write the row (so no transaction is held across the probe).
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                row = await session.get(McpDispatchAttemptModel, call.attempt_id)
                assert row is not None
                observed["owner"] = row.reconcile_lease_owner
                observed["expires"] = row.reconcile_lease_expires_at
                row.reconcile_probe_count = row.reconcile_probe_count
                session.add(row)

    clock = {"now": parked.dispatched + timedelta(seconds=5)}
    probe = ScriptedProbe(tool, ProviderOutcome.UNKNOWN, on_lookup=during_probe)
    assert (await _worker(probe, clock).run_once()).still_unknown == 1
    assert observed["owner"] is not None
    assert to_naive_utc(observed["expires"]) == clock["now"] + timedelta(seconds=60)


@pytest.mark.anyio
async def test_concurrent_workers_partition_and_lost_lease_resolves_nothing(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-lease-race"
    try:
        parked = await _park(client, tool, "rx-1")
    finally:
        get_service_registry().unregister_local(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=QUIESCENCE + 5)}
    probe = ScriptedProbe(tool, ProviderOutcome.NOT_EXECUTED)
    a = _worker(probe, clock)
    b = _worker(probe, clock)

    claimed_a = await a.claim_due_calls(owner="owner-a")
    assert [c.attempt_id for c in claimed_a] == [parked.attempt.attempt_id]
    # The same row cannot be leased twice while the lease is live.
    assert await b.claim_due_calls(owner="owner-b") == []

    # A stalls past its lease; B takes over and resolves.
    clock["now"] += timedelta(seconds=61)
    claimed_b = await b.claim_due_calls(owner="owner-b")
    assert len(claimed_b) == 1
    counts: dict[str, int] = dict.fromkeys(
        (
            "probed",
            "probe_errors",
            "resolved_executed",
            "resolved_not_executed",
            "refunded",
            "deferred_quiescence",
            "still_unknown",
            "lost_leases",
        ),
        0,
    )
    await a._probe_and_resolve(claimed_a[0], owner="owner-a", counts=counts)
    assert counts["lost_leases"] == 1 and counts["refunded"] == 0
    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status is None and row.debit_refunded_at is None

    await b._probe_and_resolve(claimed_b[0], owner="owner-b", counts=counts)
    assert counts["refunded"] == 1
    charge = parked.attempt.ledger_entry_id
    assert charge is not None
    assert len(await _refunds(charge)) == 1
    # A sweep that lost its row never asked the provider.
    assert len(probe.seen) == 1


@pytest.mark.anyio
async def test_lease_is_renewed_before_a_probe_queued_behind_others(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-lease-renew"
    try:
        parked = await _park(client, tool, "rn-1")
    finally:
        get_service_registry().unregister_local(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=5)}
    probe = ScriptedProbe(tool, ProviderOutcome.EXECUTED)
    worker = _worker(probe, clock)
    claimed = await worker.claim_due_calls(owner="owner-a")
    assert len(claimed) == 1

    # Earlier probes in the batch used up this row's claim-time lease, but no
    # other sweep took it: the answer must still be recorded.
    clock["now"] += timedelta(seconds=61)
    counts: dict[str, int] = dict.fromkeys(
        ("probed", "probe_errors", "resolved_executed", "lost_leases"), 0
    )
    await worker._probe_and_resolve(claimed[0], owner="owner-a", counts=counts)
    assert (counts["resolved_executed"], counts["lost_leases"]) == (1, 0)
    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status == "executed"


@pytest.mark.anyio
async def test_tool_without_status_endpoint_stays_in_manual_review(
    client: AsyncClient, clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    tool = "reconcile-manual-review"
    try:
        parked = await _park(client, tool, "rm-1")
    finally:
        get_service_registry().unregister_local(tool)
    before = await _money_snapshot(parked.wallet_id, parked.permit_id)
    clock = {"now": parked.dispatched + timedelta(days=30)}

    # No status endpoint at all.
    worker = _worker(None, clock, alert_age_seconds=60)
    with caplog.at_level("WARNING", logger="app.services.upstream_reconcile"):
        sweep = await worker.run_once()
    assert (sweep.probed, sweep.aged_alerts) == (0, 1)
    aged = [r for r in caplog.records if r.message == "mcp_delivery_uncertain_aged"]
    assert aged and aged[0].manual_review is True

    # A status endpoint for a different tool never sees this call.
    other = ScriptedProbe("some-other-tool")
    assert (await _worker(other, clock).run_once()).probed == 0
    assert other.seen == []
    # Same tool id on a different origin is not this upstream either.
    foreign = ScriptedProbe(tool, upstream_origin="https://elsewhere.example.com")
    assert (await _worker(foreign, clock).run_once()).probed == 0

    row = await _attempt(parked.attempt.attempt_id)
    assert row.reconcile_status is None and row.reconcile_lease_owner is None
    assert await _money_snapshot(parked.wallet_id, parked.permit_id) == before


@pytest.mark.anyio
async def test_age_alerts_page_past_the_first_batch(
    client: AsyncClient, clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    parked = []
    for index in range(2):
        tool = f"reconcile-aged-page-{index}"
        try:
            parked.append(await _park(client, tool, f"ap-{index}"))
        finally:
            get_service_registry().unregister_local(tool)
    clock = {"now": max(p.dispatched for p in parked) + timedelta(days=1)}
    # Manual-review rows never resolve, so with a batch of one the second
    # call is only reached if the alert query pages past the first.
    worker = _worker(None, clock, alert_age_seconds=60, limit=1)
    with caplog.at_level("WARNING", logger="app.services.upstream_reconcile"):
        sweeps = [(await worker.run_once()).aged_alerts for _ in range(4)]
    assert sweeps == [1, 1, 0, 0]
    alerted = {
        r.dispatch_attempt_id
        for r in caplog.records
        if r.message == "mcp_delivery_uncertain_aged"
    }
    assert alerted == {p.attempt.attempt_id for p in parked}


@pytest.mark.anyio
async def test_tampered_receipt_is_never_resolved(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-tampered"
    try:
        parked = await _park(client, tool, "rt-1")
    finally:
        get_service_registry().unregister_local(tool)
    async with get_session_factory()() as session:
        row = await session.get(ReceiptModel, parked.receipt["receipt_id"])
        assert row is not None
        row.credits_charged = Decimal("0")
        session.add(row)
        await session.commit()
    probe = ScriptedProbe(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=QUIESCENCE + 5)}
    sweep = await _worker(probe, clock).run_once()
    assert (sweep.probe_errors, sweep.refunded) == (1, 0)
    assert probe.seen == []
    assert (await _attempt(parked.attempt.attempt_id)).reconcile_status is None


@pytest.mark.anyio
async def test_gates_still_refuse_an_unreconciled_delivery_uncertain(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-gates"
    try:
        parked = await _park(client, tool, "rg-1")
    finally:
        get_service_registry().unregister_local(tool)
    with pytest.raises(PermitError) as excinfo:
        await get_permit_service().release_dispatch_budget_once(
            parked.attempt.attempt_id, is_system=True
        )
    assert excinfo.value.reason == "dispatch_budget_release_state_invalid"
    with pytest.raises(DispatchAttemptConflictError):
        await get_mcp_dispatch_attempt_service().mark_debit_refunded(
            attempt_id=parked.attempt.attempt_id,
            ledger_entry_id=parked.attempt.ledger_entry_id or "",
        )
    # Review status (refund policy off) does not unlock the gates either.
    async with get_session_factory()() as session:
        row = await session.get(McpDispatchAttemptModel, parked.attempt.attempt_id)
        assert row is not None
        row.reconcile_status = "not_executed_review"
        session.add(row)
        await session.commit()
    with pytest.raises(PermitError):
        await get_permit_service().release_dispatch_budget_once(
            parked.attempt.attempt_id, is_system=True
        )


# --- the probe itself --------------------------------------------------------


def _configuration(**overrides: Any) -> UpstreamMcpConfiguration:
    values: dict[str, Any] = {
        "MCP_UPSTREAM_URL": "https://partner.example.com/mcp",
        "MCP_UPSTREAM_TOOL_NAME": "partner_tool",
        "MCP_UPSTREAM_PUBLIC_TOOL_ID": "partner.tool",
        "MCP_UPSTREAM_BEARER_TOKEN": SecretStr(TOKEN),
        "MCP_UPSTREAM_CREDITS_PER_CALL": Decimal("1"),
        "MCP_UPSTREAM_STATUS_URL": STATUS_URL,
        "ENVIRONMENT": "test",
    }
    values.update(overrides)
    return UpstreamMcpConfiguration.from_settings(Settings(**values))


async def _public_resolver(host: str, port: int | None) -> list[str]:
    return ["93.184.216.34"]


def _probe(
    handler: Callable[[httpx.Request], httpx.Response],
) -> UpstreamMcpStatusProbe:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {TOKEN}"},
        follow_redirects=False,
    )
    return UpstreamMcpStatusProbe(
        _configuration(), http_client=client, resolver=_public_resolver
    )


def _echo(status: Any, **extra: Any) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        body = {
            "invocation_id": sent["invocation_id"],
            "idempotency_key": sent.get("idempotency_key"),
            "status": status,
            "provider_request_id": "prov-9",
        }
        body.update(extra)
        return httpx.Response(200, json=body)

    return handler


@pytest.mark.anyio
async def test_probe_sends_bound_request_with_operator_credential() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _echo("executed")(request)

    answer = await _probe(handler).lookup(invocation_id="idm-1", idempotency_key="k-1")
    assert answer.outcome is UpstreamStatusOutcome.EXECUTED
    assert answer.provider_request_id == "prov-9"
    request = seen[0]
    assert request.method == "POST"
    # Connected to the one validated address, with Host (and SNI) preserved.
    assert request.url.host == "93.184.216.34"
    assert request.url.path == "/agent-middleware/status"
    assert request.headers["host"] == "partner.example.com"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "tool": "partner_tool",
        "invocation_id": "idm-1",
        "idempotency_key": "k-1",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("handler", "expected", "reason"),
    [
        (_echo("not_executed"), UpstreamStatusOutcome.NOT_EXECUTED, "attested"),
        (_echo("pending"), UpstreamStatusOutcome.UNKNOWN, "unattested"),
        (_echo("NOT_EXECUTED"), UpstreamStatusOutcome.UNKNOWN, "unattested"),
        (_echo(True), UpstreamStatusOutcome.UNKNOWN, "unattested"),
        (
            _echo("not_executed", idempotency_key="someone-else"),
            UpstreamStatusOutcome.UNKNOWN,
            "binding_mismatch",
        ),
        (
            _echo("not_executed", invocation_id="idm-other"),
            UpstreamStatusOutcome.UNKNOWN,
            "binding_mismatch",
        ),
        # A 404 is never proof of non-execution, whatever its body says.
        (
            lambda r: httpx.Response(
                404, json={"status": "not_executed", "invocation_id": "idm-1"}
            ),
            UpstreamStatusOutcome.UNKNOWN,
            "not_found",
        ),
        (
            lambda r: httpx.Response(202, json={"status": "not_executed"}),
            UpstreamStatusOutcome.UNKNOWN,
            "unattested",
        ),
    ],
)
async def test_probe_classification(
    handler: Callable[[httpx.Request], httpx.Response],
    expected: UpstreamStatusOutcome,
    reason: str,
) -> None:
    answer = await _probe(handler).lookup(invocation_id="idm-1", idempotency_key="k-1")
    assert (answer.outcome, answer.reason) == (expected, reason)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, json={"status": "not_executed"}),
        lambda r: httpx.Response(302, headers={"Location": "https://evil.example"}),
        lambda r: httpx.Response(401),
        lambda r: httpx.Response(200, content=b"not json"),
        lambda r: httpx.Response(200, json=["not_executed"]),
        lambda r: httpx.Response(200, content=b"{" + b" " * 20_000 + b"}"),
        _echo("executed", note=f"echo {TOKEN}"),
    ],
    ids=["5xx", "redirect", "401", "non-json", "non-object", "oversize", "secret"],
)
async def test_probe_failures_raise_and_never_attest(
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    with pytest.raises(UpstreamStatusProbeError):
        await _probe(handler).lookup(invocation_id="idm-1", idempotency_key="k-1")


@pytest.mark.anyio
async def test_probe_without_forwarded_key_binds_to_invocation_id() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        seen.append(sent)
        return httpx.Response(
            200, json={"invocation_id": sent["invocation_id"], "status": "executed"}
        )

    answer = await _probe(handler).lookup(invocation_id="idm-1", idempotency_key=None)
    assert answer.outcome is UpstreamStatusOutcome.EXECUTED
    assert "idempotency_key" not in seen[0]


@pytest.mark.anyio
async def test_probe_refuses_private_destination() -> None:
    async def private(host: str, port: int | None) -> list[str]:
        return ["10.0.0.5"]

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_echo("executed")),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    probe = UpstreamMcpStatusProbe(
        _configuration(), http_client=client, resolver=private
    )
    with pytest.raises(UpstreamStatusProbeError) as excinfo:
        await probe.lookup(invocation_id="idm-1", idempotency_key="k-1")
    assert excinfo.value.code == "upstream_status_destination_rejected"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"MCP_UPSTREAM_STATUS_URL": "https://other.example.com/status"}, "origin"),
        ({"MCP_UPSTREAM_STATUS_URL": "https://partner.example.com:8443/s"}, "origin"),
        ({"MCP_UPSTREAM_STATUS_URL": "http://partner.example.com/status"}, "origin"),
        ({"MCP_UPSTREAM_STATUS_URL": STATUS_URL + "?key=1"}, "query"),
        ({"MCP_UPSTREAM_STATUS_URL": f"{STATUS_URL}/{TOKEN}"}, "differ"),
        ({"MCP_UPSTREAM_STATUS_URL": "https://partner.example.com/mcp"}, "differ"),
        ({"MCP_UPSTREAM_STATUS_TIMEOUT_SECONDS": 0}, "TIMEOUT"),
        ({"MCP_UPSTREAM_STATUS_TIMEOUT_SECONDS": float("nan")}, "TIMEOUT"),
    ],
)
def test_status_url_configuration_fails_closed(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(UpstreamMcpConfigurationError) as excinfo:
        _configuration(**overrides)
    assert message in excinfo.value.detail


def test_configured_probe_requires_status_url_and_quiescence_floors() -> None:
    base = {
        "MCP_UPSTREAM_ENABLED": True,
        "MCP_UPSTREAM_URL": "https://partner.example.com/mcp",
        "MCP_UPSTREAM_TOOL_NAME": "partner_tool",
        "MCP_UPSTREAM_PUBLIC_TOOL_ID": "partner.tool",
        "MCP_UPSTREAM_BEARER_TOKEN": SecretStr(TOKEN),
        "MCP_UPSTREAM_CREDITS_PER_CALL": Decimal("1"),
    }
    assert build_configured_probe(Settings(**base)) is None
    probe = build_configured_probe(Settings(**base, MCP_UPSTREAM_STATUS_URL=STATUS_URL))
    assert isinstance(probe, UpstreamStatusEndpointProbe)
    assert (probe.public_tool_id, probe.upstream_origin) == (
        "partner.tool",
        "https://partner.example.com",
    )
    # Draining new dispatch keeps probing calls that are already parked.
    drained = {**base, "MCP_UPSTREAM_ENABLED": False}
    assert isinstance(
        build_configured_probe(Settings(**drained, MCP_UPSTREAM_STATUS_URL=STATUS_URL)),
        UpstreamStatusEndpointProbe,
    )
    # A lease that cannot outlive one probe (connect 5 s + status 10 s) is
    # refused rather than letting the answer arrive after the row is free.
    with pytest.raises(ValueError, match="lease_shorter_than_probe"):
        build_configured_probe(
            Settings(
                **base,
                MCP_UPSTREAM_STATUS_URL=STATUS_URL,
                UPSTREAM_RECONCILE_LEASE_SECONDS=15,
            )
        )

    # Default: fixed rolling-deployment lifetime + skew.
    assert quiescence_allowance_seconds(Settings(**base)) == 11_430 + 300
    # An explicit value below this deployment's live call lifetime is floored.
    floored = Settings(
        **base,
        UPSTREAM_RECONCILE_UPSTREAM_TIMEOUT_SECONDS=1,
        UPSTREAM_RECONCILE_CLOCK_SKEW_SECONDS=0,
    )
    assert quiescence_allowance_seconds(floored) == 5 + 3 * 30
    with pytest.raises(ValueError, match="quiescence"):
        quiescence_allowance_seconds(
            Settings(**base, UPSTREAM_RECONCILE_CLOCK_SKEW_SECONDS=-1)
        )


@pytest.mark.anyio
async def test_no_credential_material_is_stored_on_attempt_rows(
    client: AsyncClient, clean_database
) -> None:
    tool = "reconcile-no-secret"
    try:
        parked = await _park(client, tool, "rs-1")
    finally:
        get_service_registry().unregister_local(tool)
    clock = {"now": parked.dispatched + timedelta(seconds=5)}
    await _worker(ScriptedProbe(tool, ProviderOutcome.UNKNOWN), clock).run_once()
    async with get_session_factory()() as session:
        row = await session.get(McpDispatchAttemptModel, parked.attempt.attempt_id)
        assert row is not None
        dumped = json.dumps(row.model_dump(), default=str)
        assert TOKEN not in dumped and "Bearer" not in dumped
        total = (
            await session.execute(
                select(func.count()).select_from(McpDispatchAttemptModel)
            )
        ).scalar_one()
        assert total == 1
