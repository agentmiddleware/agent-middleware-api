from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    ControlPlaneAuditEventModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    ReceiptModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.audit_log import record_audit_event
from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    get_idempotency_service,
)
from app.services.mcp_dispatch_attempts import get_mcp_dispatch_attempt_service
from app.services.mcp_dispatch_reconciliation import (
    get_mcp_dispatch_reconciliation_service,
)
from app.services.permits import get_permit_service
from app.services.receipts import get_receipt_service
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

CREDITS = Decimal("1.5")
ENDPOINT = "/mcp/messages"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@dataclass(frozen=True)
class SeededAttempt:
    wallet_id: str
    key_id: str
    permit_id: str
    tool_name: str
    idempotency_key: str
    request_payload: dict[str, Any]
    idempotency_endpoint: str
    attempt_id: str
    ledger_entry_id: str | None


async def _seed_attempt(
    client: AsyncClient,
    *,
    suffix: str,
    state: str,
    attach_charge: bool = True,
    result_payload: dict[str, Any] | None = None,
    error_code: str | None = None,
    idempotency_endpoint: str = ENDPOINT,
) -> SeededAttempt:
    provisioned = await provision_agent_wallet(client)
    tool_name = f"reconcile-{suffix}"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"reconcile-permit-{suffix}",
    )
    validation = await get_permit_service().authorize_and_reserve(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        tool_name=tool_name,
        estimated_credits=CREDITS,
        key_id=provisioned["key_id"],
    )
    assert validation.allowed is True

    request_payload = {
        "tool": tool_name,
        "arguments": {"value": suffix},
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
    }
    idempotency_key = f"reconcile-invoke-{suffix}"
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=idempotency_endpoint,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    dispatch = get_mcp_dispatch_attempt_service()
    attempt = await dispatch.prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="partner_lookup",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=CREDITS,
    )
    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path=ENDPOINT,
        operation_key=begun.record_id,
    )
    assert hasattr(charge, "entry_id")
    ledger_entry_id = charge.entry_id
    if attach_charge:
        attempt = await dispatch.attach_charge(
            attempt_id=attempt.attempt_id,
            ledger_entry_id=ledger_entry_id,
            credits_charged=CREDITS,
        )
    if state != "prepared":
        attempt = await dispatch.mark_dispatched(attempt.attempt_id)
    if state not in {"prepared", "dispatched"}:
        attempt = await dispatch.complete(
            attempt_id=attempt.attempt_id,
            state=state,
            result_payload=result_payload,
            error_code=error_code,
            max_result_bytes=4096,
        )
    await _make_stale(attempt.attempt_id)
    return SeededAttempt(
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        permit_id=permit["permit_id"],
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        idempotency_endpoint=idempotency_endpoint,
        attempt_id=attempt.attempt_id,
        ledger_entry_id=ledger_entry_id,
    )


async def _make_stale(attempt_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            attempt = await session.get(McpDispatchAttemptModel, attempt_id)
            assert attempt is not None
            attempt.updated_at = utc_now() - timedelta(minutes=10)
            session.add(attempt)


async def _attempt(attempt_id: str) -> McpDispatchAttemptModel:
    context = await get_mcp_dispatch_attempt_service().get_context(attempt_id)
    assert context is not None
    return context.attempt


async def _ledger_counts(wallet_id: str) -> tuple[int, int]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(LedgerEntryModel.action, func.count())
                .where(LedgerEntryModel.wallet_id == wallet_id)
                .group_by(LedgerEntryModel.action)
            )
        ).all()
    counts = {str(action): int(count) for action, count in rows}
    return counts.get("debit", 0), counts.get("refund", 0)


async def _replay(seed: SeededAttempt) -> tuple[dict[str, Any], int]:
    record = await get_idempotency_service().get_record(
        wallet_id=seed.wallet_id,
        endpoint=seed.idempotency_endpoint,
        idempotency_key=seed.idempotency_key,
    )
    assert record is not None
    assert record.response_json is not None
    return json.loads(record.response_json), record.status_code


@pytest.mark.anyio
async def test_effect_free_stale_mcp_identity_is_released_for_safe_retry(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned = await provision_agent_wallet(client)
    payload = {
        "tool_name": "partner-unstarted",
        "arguments": {"value": "safe"},
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": "permit-never-reserved",
    }
    idempotency_key = "unstarted-before-atomic-prepare"
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=idempotency_key,
        request_payload=payload,
        operation_kind="upstream_mcp",
    )
    factory = get_session_factory()
    async with factory() as session:
        record = await session.get(IdempotencyRecordModel, begun.record_id)
        assert record is not None
        record.created_at = utc_now() - timedelta(minutes=10)
        session.add(record)
        await session.commit()

    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=300
    )

    assert (repaired, needs_review) == (1, 0)
    assert (
        await get_idempotency_service().get_record(
            wallet_id=provisioned["agent_wallet_id"],
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key=idempotency_key,
        )
        is None
    )


@pytest.mark.anyio
async def test_stale_local_identity_is_not_deleted_without_compensation_proof(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned = await provision_agent_wallet(client)
    idempotency_key = "local-reservation-order-is-different"
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=idempotency_key,
        request_payload={"tool_name": "local-tool", "arguments": {}},
        operation_kind="local",
    )
    factory = get_session_factory()
    async with factory() as session:
        record = await session.get(IdempotencyRecordModel, begun.record_id)
        assert record is not None
        record.created_at = utc_now() - timedelta(minutes=10)
        session.add(record)
        await session.commit()

    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=300
    )

    assert (repaired, needs_review) == (0, 0)
    assert (
        await get_idempotency_service().get_record(
            wallet_id=provisioned["agent_wallet_id"],
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key=idempotency_key,
        )
        is not None
    )


@pytest.mark.anyio
async def test_stale_prepared_adopts_debit_refunds_and_finalizes_once(
    client: AsyncClient,
    clean_database,
) -> None:
    seed = await _seed_attempt(
        client,
        suffix="prepared-after-debit",
        state="prepared",
        attach_charge=False,
    )
    before = await get_agent_money().get_wallet(seed.wallet_id)
    assert before is not None
    assert before.balance == Decimal("998.5")

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)

    assert result.prepared_finalized == 1
    assert result.failed_attempt_ids == ()
    attempt = await _attempt(seed.attempt_id)
    assert attempt.state == "returned_error"
    assert attempt.ledger_entry_id == seed.ledger_entry_id
    assert attempt.debit_refunded_at is not None
    assert attempt.budget_released_at is not None
    receipt = await get_receipt_service().get_receipt_by_idempotency_record_id(
        attempt.idempotency_record_id
    )
    assert receipt is not None
    assert receipt.outcome == "failed_refunded"
    assert receipt.credits_charged == Decimal("0")
    assert receipt.ledger_entry_id == seed.ledger_entry_id
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert (valid, reason) == (True, None)
    after = await get_agent_money().get_wallet(seed.wallet_id)
    permit = await get_permit_service().get_permit(seed.permit_id)
    assert after is not None and after.balance == Decimal("1000")
    assert permit is not None and permit.spent_credits == Decimal("0")
    assert await _ledger_counts(seed.wallet_id) == (1, 1)
    replay, status = await _replay(seed)
    assert status == 502
    assert replay["error"] == "failed_refunded"
    assert replay["receipt"]["receipt_id"] == receipt.receipt_id

    again = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=0)
    assert again.repaired == 0
    assert await _ledger_counts(seed.wallet_id) == (1, 1)
    permit = await get_permit_service().get_permit(seed.permit_id)
    assert permit is not None and permit.spent_credits == Decimal("0")


@pytest.mark.anyio
async def test_stale_dispatched_becomes_charged_delivery_uncertain_without_retry(
    client: AsyncClient,
    clean_database,
) -> None:
    seed = await _seed_attempt(
        client,
        suffix="dispatched-timeout",
        state="dispatched",
    )

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)

    assert result.dispatched_uncertain == 1
    assert result.failed_attempt_ids == ()
    attempt = await _attempt(seed.attempt_id)
    assert attempt.state == "delivery_uncertain"
    assert attempt.debit_refunded_at is None
    assert attempt.budget_released_at is None
    assert await _ledger_counts(seed.wallet_id) == (1, 0)
    wallet = await get_agent_money().get_wallet(seed.wallet_id)
    permit = await get_permit_service().get_permit(seed.permit_id)
    assert wallet is not None and wallet.balance == Decimal("998.5")
    assert permit is not None and permit.spent_credits == CREDITS
    receipt = await get_receipt_service().get_receipt_by_idempotency_record_id(
        attempt.idempotency_record_id
    )
    assert receipt is not None
    assert receipt.outcome == "delivery_uncertain"
    assert receipt.credits_charged == CREDITS
    replay, status = await _replay(seed)
    assert status == 504
    assert replay["error"] == "delivery_uncertain"
    assert replay["dispatch"] == {
        "attempt_id": seed.attempt_id,
        "state": "delivery_uncertain",
    }

    again = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=0)
    assert again.repaired == 0
    assert await _ledger_counts(seed.wallet_id) == (1, 0)


@pytest.mark.anyio
async def test_terminal_success_is_reconstructed_from_bounded_result(
    client: AsyncClient,
    clean_database,
) -> None:
    upstream_result = {
        "content": [{"type": "text", "text": "confirmed"}],
        "structuredContent": {"answer": 42},
        "isError": False,
    }
    seed = await _seed_attempt(
        client,
        suffix="success-result-persisted",
        state="succeeded",
        result_payload=upstream_result,
    )

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)

    assert result.terminal_recovered == 1
    attempt = await _attempt(seed.attempt_id)
    receipt = await get_receipt_service().get_receipt_by_idempotency_record_id(
        attempt.idempotency_record_id
    )
    assert receipt is not None
    assert receipt.outcome == "success"
    assert receipt.response_hash == attempt.response_hash
    replay, status = await _replay(seed)
    assert status == 200
    assert replay["content"] == upstream_result["content"]
    assert replay["structuredContent"] == upstream_result["structuredContent"]
    assert replay["receipt"]["receipt_id"] == receipt.receipt_id
    assert await _ledger_counts(seed.wallet_id) == (1, 0)


@pytest.mark.anyio
async def test_existing_receipt_missing_idempotency_completion_replays_full_result(
    client: AsyncClient,
    clean_database,
) -> None:
    upstream_result = {
        "content": [{"type": "text", "text": "original response"}],
        "structuredContent": {"source": "partner"},
        "isError": False,
    }
    seed = await _seed_attempt(
        client,
        suffix="receipt-before-idem-complete",
        state="succeeded",
        result_payload=upstream_result,
        idempotency_endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    )
    attempt = await _attempt(seed.attempt_id)
    audit = await record_audit_event(
        event="mcp.invoke",
        wallet_id=seed.wallet_id,
        tool=seed.tool_name,
        endpoint=ENDPOINT,
        auth_source="db",
        key_id=seed.key_id,
        ok=True,
        metadata={
            "transport": "jsonrpc",
            "permit_id": seed.permit_id,
            "request_hash": attempt.request_hash,
            "ledger_entry_id": seed.ledger_entry_id,
            "dispatch_attempt_id": seed.attempt_id,
            "dispatch_state": "succeeded",
            "dispatch_response_hash": attempt.response_hash,
            "upstream_tool_name": attempt.upstream_tool_name,
            "upstream_origin": attempt.upstream_origin,
        },
    )
    receipt = await get_receipt_service().create_receipt(
        idempotency_record_id=attempt.idempotency_record_id,
        dispatch_attempt_id=seed.attempt_id,
        permit_id=seed.permit_id,
        wallet_id=seed.wallet_id,
        key_id=seed.key_id,
        tool=seed.tool_name,
        request_payload=None,
        request_hash=attempt.request_hash,
        response_payload=upstream_result,
        ledger_entry_id=seed.ledger_entry_id,
        credits_authorized=CREDITS,
        credits_charged=CREDITS,
        outcome="success",
        audit_event_id=audit.event_id,
    )
    await get_idempotency_service().mark_charged(
        wallet_id=seed.wallet_id,
        endpoint=seed.idempotency_endpoint,
        idempotency_key=seed.idempotency_key,
        ledger_entry_id=seed.ledger_entry_id or "",
    )
    await _make_stale(seed.attempt_id)

    # Sweep order cannot let the generic cleanup replace the stored upstream
    # result with its receipt-only fallback response.
    (
        generic_repaired,
        generic_manual,
    ) = await get_idempotency_service().reconcile_stuck_records(idle_seconds=0)
    assert (generic_repaired, generic_manual) == (0, 0)
    record_before = await get_idempotency_service().get_record(
        wallet_id=seed.wallet_id,
        endpoint=seed.idempotency_endpoint,
        idempotency_key=seed.idempotency_key,
    )
    assert record_before is not None and record_before.response_json is None

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)

    assert result.idempotency_recovered == 1
    replay, status = await _replay(seed)
    assert status == 200
    assert replay["content"] == upstream_result["content"]
    assert replay["structuredContent"] == upstream_result["structuredContent"]
    assert replay["receipt"]["receipt_id"] == receipt.receipt_id
    factory = get_session_factory()
    async with factory() as session:
        receipt_count = await session.scalar(
            select(func.count()).select_from(ReceiptModel)
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(ControlPlaneAuditEventModel)
            .where(
                ControlPlaneAuditEventModel.tool == seed.tool_name,
                ControlPlaneAuditEventModel.event == "mcp.invoke",
            )
        )
    assert int(receipt_count or 0) == 1
    assert int(audit_count or 0) == 1


@pytest.mark.anyio
async def test_terminal_returned_error_completes_crash_compensation(
    client: AsyncClient,
    clean_database,
) -> None:
    upstream_result = {
        "content": [{"type": "text", "text": "partner rejected"}],
        "isError": True,
    }
    seed = await _seed_attempt(
        client,
        suffix="returned-before-refund",
        state="returned_error",
        result_payload=upstream_result,
        error_code="upstream_returned_error",
    )

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)

    assert result.terminal_recovered == 1
    attempt = await _attempt(seed.attempt_id)
    assert attempt.debit_refunded_at is not None
    assert attempt.budget_released_at is not None
    assert await _ledger_counts(seed.wallet_id) == (1, 1)
    permit = await get_permit_service().get_permit(seed.permit_id)
    assert permit is not None and permit.spent_credits == Decimal("0")
    receipt = await get_receipt_service().get_receipt_by_idempotency_record_id(
        attempt.idempotency_record_id
    )
    assert receipt is not None and receipt.outcome == "failed_refunded"
    assert receipt.response_hash == attempt.response_hash
    replay, status = await _replay(seed)
    assert status == 502
    assert replay["error"] == "upstream_returned_error"
    assert replay["upstream_result"] == upstream_result


@pytest.mark.anyio
async def test_crash_after_budget_release_does_not_release_unrelated_reservation(
    client: AsyncClient,
    clean_database,
) -> None:
    seed = await _seed_attempt(
        client,
        suffix="after-budget-release",
        state="returned_error",
        result_payload={"error": "confirmed"},
        error_code="upstream_returned_error",
    )
    dispatch = get_mcp_dispatch_attempt_service()
    await get_agent_money().refund_charge(
        wallet_id=seed.wallet_id,
        charge_entry_id=seed.ledger_entry_id or "",
    )
    await dispatch.mark_debit_refunded(
        attempt_id=seed.attempt_id,
        ledger_entry_id=seed.ledger_entry_id or "",
    )
    released = await get_permit_service().release_dispatch_budget_once(seed.attempt_id)
    assert released is True
    # A later reservation on the same permit must survive reconciliation.
    await get_permit_service().reserve_budget(seed.permit_id, Decimal("2"))
    await _make_stale(seed.attempt_id)

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)
    assert result.terminal_recovered == 1
    permit = await get_permit_service().get_permit(seed.permit_id)
    assert permit is not None and permit.spent_credits == Decimal("2")
    assert await _ledger_counts(seed.wallet_id) == (1, 1)

    await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=0)
    permit = await get_permit_service().get_permit(seed.permit_id)
    assert permit is not None and permit.spent_credits == Decimal("2")


@pytest.mark.anyio
async def test_terminal_response_rejected_retains_charge_and_is_replayable(
    client: AsyncClient,
    clean_database,
) -> None:
    seed = await _seed_attempt(
        client,
        suffix="response-rejected",
        state="response_rejected",
        result_payload={"error": "response_rejected"},
        error_code="upstream_response_too_large",
    )

    result = await get_mcp_dispatch_reconciliation_service().reconcile(idle_seconds=300)

    assert result.terminal_recovered == 1
    attempt = await _attempt(seed.attempt_id)
    receipt = await get_receipt_service().get_receipt_by_idempotency_record_id(
        attempt.idempotency_record_id
    )
    assert receipt is not None
    assert receipt.outcome == "response_rejected"
    assert receipt.credits_charged == CREDITS
    assert await _ledger_counts(seed.wallet_id) == (1, 0)
    replay, status = await _replay(seed)
    assert status == 502
    assert replay["error"] == "response_rejected"


@pytest.mark.anyio
async def test_dispatch_summary_exposes_only_counts_and_backlog(
    client: AsyncClient,
    clean_database,
) -> None:
    await _seed_attempt(
        client,
        suffix="metrics-prepared",
        state="prepared",
    )
    await _seed_attempt(
        client,
        suffix="metrics-terminal",
        state="succeeded",
        result_payload={"content": [], "isError": False},
    )

    metrics = await get_mcp_dispatch_attempt_service().summarize(idle_seconds=300)

    assert metrics.state_counts == {"prepared": 1, "succeeded": 1}
    assert metrics.stale_active == 1
    assert metrics.unfinalized_terminal == 1
    assert metrics.terminal_idempotency_incomplete == 0
    assert metrics.reconciliation_backlog == 2
    assert "payload" not in repr(metrics)
