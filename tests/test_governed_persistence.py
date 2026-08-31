from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    HumanApprovalModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitCallReservationModel,
    PermitModel,
    ReceiptModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.billing_engine import LedgerOperationConflictError
from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    IdempotencyBegin,
    get_idempotency_service,
)
from app.services.human_approval import invoke_request_hash
from app.services.mcp_dispatch_attempts import (
    DispatchAttemptConflictError,
    DispatchAttemptError,
    DispatchClaimUnavailableError,
    DispatchPrepareCommitUncertainError,
    DispatchPrepareRolledBackError,
    DispatchResultTooLargeError,
    McpDispatchAttemptService,
    dispatch_reconciliation_idle_seconds,
    get_mcp_dispatch_attempt_service,
)
from app.services.permits import PermitError, PermitValidation, get_permit_service
from app.services.receipts import ReceiptError, get_receipt_service
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


async def _seed_governed_identity(
    client: AsyncClient,
    *,
    suffix: str,
    requires_human_approval: bool = False,
) -> tuple[dict, dict, dict, IdempotencyBegin]:
    provisioned = await provision_agent_wallet(client)
    tool_name = f"partner-tool-{suffix}"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"permit-{suffix}",
        requires_human_approval=requires_human_approval,
    )
    request_payload = {"tool": tool_name, "arguments": {"value": suffix}}
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/mcp/messages",
        idempotency_key=f"invoke-{suffix}",
        request_payload=request_payload,
    )
    assert begun.replay is None
    return provisioned, permit, request_payload, begun


async def _create_constrained_permit(
    client: AsyncClient,
    *,
    suffix: str,
    max_calls: int | None = None,
    aggregate_value_cap: Decimal | None = None,
) -> tuple[dict, dict, str]:
    provisioned = await provision_agent_wallet(client)
    tool_name = f"constrained-partner-{suffix}"
    payload: dict[str, object] = {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": [tool_name],
        "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
        "max_credits": "10",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    if max_calls is not None:
        payload["max_calls_per_tool"] = {tool_name: max_calls}
    if aggregate_value_cap is not None:
        payload["aggregate_value_cap"] = str(aggregate_value_cap)
    response = await client.post(
        "/v1/permits",
        json=payload,
        headers={"X-API-Key": "test-key", "Idempotency-Key": f"permit-{suffix}"},
    )
    assert response.status_code == 201
    return provisioned, response.json(), tool_name


async def _prepare_constrained_attempt(
    *,
    suffix: str,
    provisioned: dict,
    permit: dict,
    tool_name: str,
) -> tuple[IdempotencyBegin, PermitValidation, McpDispatchAttemptModel | None]:
    arguments = {"value": suffix}
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/mcp/invoke",
        idempotency_key=f"invoke-{suffix}",
        request_payload={
            "tool_name": tool_name,
            "arguments": arguments,
            "wallet_id": provisioned["agent_wallet_id"],
            "permit_id": permit["permit_id"],
        },
        operation_kind="upstream_mcp",
    )
    (
        validation,
        attempt,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="partner_lookup",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1"),
        arguments=arguments,
    )
    return begun, validation, attempt


async def _reserve_constrained_local_call(
    *,
    suffix: str,
    provisioned: dict,
    permit: dict,
    tool_name: str,
) -> tuple[IdempotencyBegin, PermitValidation]:
    arguments = {"value": suffix}
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=f"invoke-{suffix}",
        request_payload={"tool": tool_name, "arguments": arguments},
        operation_kind="local",
    )
    validation = await get_permit_service().authorize_and_reserve(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        tool_name=tool_name,
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
        arguments=arguments,
        idempotency_record_id=begun.record_id,
        request_hash=begun.request_hash,
    )
    return begun, validation


async def _store_human_approval(
    *,
    approval_id: str,
    wallet_id: str,
    permit_id: str,
    tool_name: str,
    idempotency_key: str,
    status: str = "consumed",
    request_hash: str = "a" * 64,
) -> None:
    now = utc_now()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            HumanApprovalModel(
                approval_id=approval_id,
                wallet_id=wallet_id,
                permit_id=permit_id,
                tool=tool_name,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status=status,
                simulated=True,
                requested_at=now,
                expires_at=now + timedelta(minutes=30),
                decided_at=(now if status in {"approved", "consumed"} else None),
            )
        )
        await session.commit()


async def _seed_backfilled_legacy_receipt(
    client: AsyncClient,
    *,
    suffix: str,
) -> tuple[dict, dict, dict, IdempotencyBegin, ReceiptModel]:
    """Create an old-signature receipt, then apply migration-shaped linkage."""
    provisioned, permit, request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool=f"partner-tool-{suffix}",
        request_payload=request_payload,
        response_payload={"ok": True},
        ledger_entry_id=None,
        credits_authorized=Decimal("1.5"),
        credits_charged=Decimal("0"),
        outcome="denied",
        audit_event_id=None,
    )

    factory = get_session_factory()
    async with factory() as session:
        receipt_model = await session.get(ReceiptModel, receipt.receipt_id)
        record = await session.get(IdempotencyRecordModel, begun.record_id)
        assert receipt_model is not None
        assert record is not None
        record.response_reference = receipt.receipt_id
        receipt_model.idempotency_record_id = begun.record_id
        session.add(record)
        session.add(receipt_model)
        await session.commit()
        await session.refresh(receipt_model)
        session.expunge(receipt_model)

    return provisioned, permit, request_payload, begun, receipt_model


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("first_endpoint", "second_endpoint"),
    [
        ("/mcp/messages", "/mcp/invoke"),
        ("/mcp/invoke", "/mcp/tools/partner-tool/invoke"),
    ],
)
async def test_governed_mcp_identity_is_unique_across_endpoint_generations(
    clean_database,
    first_endpoint: str,
    second_endpoint: str,
) -> None:
    """SQLite create_all enforces the same rolling-deploy identity as Postgres."""
    wallet_id = "agt-governed-identity-index"
    idempotency_key = "governed-identity-index-key"
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            WalletModel(
                wallet_id=wallet_id,
                wallet_type="agent",
                balance=Decimal("100"),
            )
        )
        await session.commit()
        session.add(
            IdempotencyRecordModel(
                record_id="idm-governed-identity-first",
                wallet_id=wallet_id,
                endpoint=first_endpoint,
                idempotency_key=idempotency_key,
                request_hash="a" * 64,
            )
        )
        await session.commit()

    async with factory() as session:
        session.add(
            IdempotencyRecordModel(
                record_id="idm-governed-identity-second",
                wallet_id=wallet_id,
                endpoint=second_endpoint,
                idempotency_key=idempotency_key,
                request_hash="b" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.wallet_id == wallet_id,
                        IdempotencyRecordModel.idempotency_key == idempotency_key,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [row.endpoint for row in rows] == [first_endpoint]


async def _seed_charged_dispatch_attempt(
    client: AsyncClient,
    *,
    suffix: str,
) -> tuple[McpDispatchAttemptService, McpDispatchAttemptModel]:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
    )
    service = get_mcp_dispatch_attempt_service()
    attempt = await service.prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=f"partner-tool-{suffix}",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
    )
    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )
    assert hasattr(charge, "entry_id")
    attached = await service.attach_charge(
        attempt_id=attempt.attempt_id,
        ledger_entry_id=charge.entry_id,
        credits_charged=Decimal("1.5"),
    )
    return service, attached


def test_dispatch_reconciliation_idle_window_covers_configured_live_call() -> None:
    assert (
        dispatch_reconciliation_idle_seconds(
            connect_timeout_seconds=5,
            call_timeout_seconds=30,
        )
        == 300
    )
    assert (
        dispatch_reconciliation_idle_seconds(
            connect_timeout_seconds=5,
            call_timeout_seconds=600,
        )
        == 1835
    )


@pytest.mark.anyio
async def test_operation_key_replays_one_debit_without_recounting_velocity(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, _permit, _payload, begun = await _seed_governed_identity(
        client,
        suffix="one-debit",
    )
    wallet_id = provisioned["agent_wallet_id"]
    money = get_agent_money()

    first = await money.charge(
        wallet_id=wallet_id,
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("2"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )
    replay = await money.charge(
        wallet_id=wallet_id,
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("2"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )

    assert first.entry_id == replay.entry_id  # type: ignore[union-attr]
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        debits = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.wallet_id == wallet_id,
                        LedgerEntryModel.operation_key == begun.record_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert wallet is not None
    assert wallet.balance == Decimal("997")
    assert wallet.hourly_spent == Decimal("3")
    assert wallet.daily_spent == Decimal("3")
    assert len(debits) == 1


@pytest.mark.anyio
async def test_operation_key_charge_atomically_checkpoints_idempotency_record(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, _permit, _payload, begun = await _seed_governed_identity(
        client,
        suffix="atomic-debit-checkpoint",
    )

    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )

    factory = get_session_factory()
    async with factory() as session:
        record = await session.get(IdempotencyRecordModel, begun.record_id)
    assert record is not None
    assert record.ledger_entry_id == charge.entry_id  # type: ignore[union-attr]

    # A legacy/partially restored row may have the operation debit but not its
    # checkpoint. Re-adoption repairs the link without charging again.
    async with factory() as session:
        async with session.begin():
            record = await session.get(IdempotencyRecordModel, begun.record_id)
            assert record is not None
            record.ledger_entry_id = None
            session.add(record)

    replay = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )
    assert replay.entry_id == charge.entry_id  # type: ignore[union-attr]
    async with factory() as session:
        record = await session.get(IdempotencyRecordModel, begun.record_id)
    assert record is not None
    assert record.ledger_entry_id == charge.entry_id  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_legacy_checkpoint_repair_rejects_cross_wallet_and_credit_entries(
    client: AsyncClient,
    clean_database,
) -> None:
    owner = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=owner["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key="legacy-checkpoint-negative",
        request_payload={"tool": "local-test", "arguments": {}},
        operation_kind="local",
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            record = await session.get(IdempotencyRecordModel, begun.record_id)
            assert record is not None
            record.created_at = utc_now() - timedelta(hours=1)
            session.add(record)
            session.add(
                LedgerEntryModel(
                    entry_id="credit-same-wallet-operation",
                    wallet_id=owner["agent_wallet_id"],
                    action="credit",
                    amount=Decimal("1"),
                    balance_after=Decimal("1001"),
                    operation_key=begun.record_id,
                )
            )
            session.add(
                LedgerEntryModel(
                    entry_id="debit-other-wallet-operation",
                    wallet_id=other["agent_wallet_id"],
                    action="debit",
                    amount=Decimal("-1"),
                    balance_after=Decimal("999"),
                    operation_key=begun.record_id,
                )
            )

    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=900
    )

    assert repaired == 0
    assert needs_review == 0
    async with factory() as session:
        record = await session.get(IdempotencyRecordModel, begun.record_id)
    assert record is not None
    assert record.ledger_entry_id is None


@pytest.mark.anyio
async def test_upstream_call_limit_counts_prepared_attempt_before_receipt(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="active-call-limit",
        max_calls=1,
    )
    _first_record, first_validation, first_attempt = await _prepare_constrained_attempt(
        suffix="active-call-limit-a",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert first_validation.allowed is True
    assert first_attempt is not None

    (
        _second_record,
        second_validation,
        second_attempt,
    ) = await _prepare_constrained_attempt(
        suffix="active-call-limit-b",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert second_validation.allowed is False
    assert second_validation.reason == "permit_max_calls_exceeded"
    assert second_attempt is None

    (
        retry_validation,
        retry_attempt,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=first_attempt.idempotency_record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="partner_lookup",
        upstream_origin="https://partner.example",
        request_hash=first_attempt.request_hash,
        credits_authorized=Decimal("1"),
        arguments={"value": "active-call-limit-a"},
    )
    assert retry_validation.allowed is True
    assert retry_attempt is not None
    assert retry_attempt.attempt_id == first_attempt.attempt_id

    factory = get_session_factory()
    async with factory() as session:
        stored_permit = await session.get(PermitModel, permit["permit_id"])
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.permit_id == permit["permit_id"])
        )
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1")
    assert attempt_count == 1


@pytest.mark.anyio
async def test_upstream_delivery_uncertain_consumes_call_limit_without_receipt(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="uncertain-call-limit",
        max_calls=1,
    )
    record, validation, prepared = await _prepare_constrained_attempt(
        suffix="uncertain-call-limit-a",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert validation.allowed is True
    assert prepared is not None
    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.PLATFORM_FEE,
        units=Decimal("10"),
        request_path="/mcp/invoke",
        operation_key=record.record_id,
    )
    prepared = await get_mcp_dispatch_attempt_service().attach_charge(
        attempt_id=prepared.attempt_id,
        ledger_entry_id=charge.entry_id,  # type: ignore[union-attr]
        credits_charged=Decimal("1"),
    )
    claimed = await get_mcp_dispatch_attempt_service().claim_dispatch(
        prepared.attempt_id
    )
    terminal = await get_mcp_dispatch_attempt_service().complete(
        attempt_id=claimed.attempt_id,
        state="delivery_uncertain",
        result_payload={"error": "delivery_uncertain"},
        error_code="delivery_uncertain",
        max_result_bytes=4096,
    )
    assert terminal.dispatched_at is not None

    (
        _blocked_record,
        blocked_validation,
        blocked_attempt,
    ) = await _prepare_constrained_attempt(
        suffix="uncertain-call-limit-b",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert blocked_validation.allowed is False
    assert blocked_validation.reason == "permit_max_calls_exceeded"
    assert blocked_attempt is None


@pytest.mark.anyio
async def test_upstream_proven_pre_dispatch_failure_releases_call_limit(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="released-call-limit",
        max_calls=1,
    )
    _record, validation, prepared = await _prepare_constrained_attempt(
        suffix="released-call-limit-a",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert validation.allowed is True
    assert prepared is not None
    terminal = await get_mcp_dispatch_attempt_service().complete_pre_dispatch_failure(
        attempt_id=prepared.attempt_id,
        expected_updated_at=prepared.updated_at,
        result_payload={"error": "pre_dispatch_failed"},
        error_code="pre_dispatch_failed",
        max_result_bytes=4096,
    )
    assert terminal.dispatched_at is None
    assert await get_permit_service().release_dispatch_budget_once(prepared.attempt_id)

    (
        _replacement_record,
        replacement_validation,
        replacement_attempt,
    ) = await _prepare_constrained_attempt(
        suffix="released-call-limit-b",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert replacement_validation.allowed is True
    assert replacement_attempt is not None


@pytest.mark.anyio
async def test_upstream_aggregate_cap_counts_and_releases_pre_dispatch_reservation(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="active-aggregate-cap",
        aggregate_value_cap=Decimal("1"),
    )
    _first_record, first_validation, first_attempt = await _prepare_constrained_attempt(
        suffix="active-aggregate-cap-a",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert first_validation.allowed is True
    assert first_attempt is not None

    (
        _blocked_record,
        blocked_validation,
        blocked_attempt,
    ) = await _prepare_constrained_attempt(
        suffix="active-aggregate-cap-b",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert blocked_validation.allowed is False
    assert blocked_validation.reason == "permit_aggregate_value_cap_exceeded"
    assert blocked_attempt is None

    terminal = await get_mcp_dispatch_attempt_service().complete_pre_dispatch_failure(
        attempt_id=first_attempt.attempt_id,
        expected_updated_at=first_attempt.updated_at,
        result_payload={"error": "pre_dispatch_failed"},
        error_code="pre_dispatch_failed",
        max_result_bytes=4096,
    )
    assert terminal.dispatched_at is None
    assert await get_permit_service().release_dispatch_budget_once(
        first_attempt.attempt_id
    )

    (
        _replacement_record,
        replacement_validation,
        replacement_attempt,
    ) = await _prepare_constrained_attempt(
        suffix="active-aggregate-cap-c",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert replacement_validation.allowed is True
    assert replacement_attempt is not None


@pytest.mark.anyio
async def test_local_call_reservation_is_adopted_and_counts_before_receipt(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="local-call-limit",
        max_calls=1,
    )
    first, first_validation = await _reserve_constrained_local_call(
        suffix="local-call-limit-a",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert first_validation.allowed is True

    replay_validation = await get_permit_service().authorize_and_reserve(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        tool_name=tool_name,
        estimated_credits=Decimal("1"),
        key_id=provisioned["key_id"],
        arguments={"value": "local-call-limit-a"},
        idempotency_record_id=first.record_id,
        request_hash=first.request_hash,
    )
    assert replay_validation.allowed is True
    with pytest.raises(PermitError, match="permit_call_reservation_conflict"):
        await get_permit_service().authorize_and_reserve(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            tool_name=tool_name,
            estimated_credits=Decimal("2"),
            key_id=provisioned["key_id"],
            arguments={"value": "local-call-limit-a"},
            idempotency_record_id=first.record_id,
            request_hash=first.request_hash,
        )

    _second, second_validation = await _reserve_constrained_local_call(
        suffix="local-call-limit-b",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert second_validation.allowed is False
    assert second_validation.reason == "permit_max_calls_exceeded"

    service = get_permit_service()
    assert await service.consume_local_call(first.record_id) is True
    assert await service.consume_local_call(first.record_id) is False
    with pytest.raises(
        PermitError,
        match="permit_call_reservation_state_invalid",
    ):
        await service.release_local_call_reservation_once(first.record_id)

    factory = get_session_factory()
    async with factory() as session:
        stored_permit = await session.get(PermitModel, permit["permit_id"])
        reservations = (
            (
                await session.execute(
                    select(PermitCallReservationModel).where(
                        PermitCallReservationModel.permit_id == permit["permit_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1")
    assert len(reservations) == 1
    assert reservations[0].idempotency_record_id == first.record_id
    assert reservations[0].state == "consumed"
    assert reservations[0].execution_started_at is not None


@pytest.mark.anyio
async def test_local_pre_execution_release_is_atomic_and_frees_call_slot(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="local-release",
        max_calls=1,
    )
    first, first_validation = await _reserve_constrained_local_call(
        suffix="local-release-a",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert first_validation.allowed is True

    service = get_permit_service()
    assert await service.release_local_call_reservation_once(first.record_id) is True
    assert await service.release_local_call_reservation_once(first.record_id) is False

    second, second_validation = await _reserve_constrained_local_call(
        suffix="local-release-b",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert second_validation.allowed is True

    factory = get_session_factory()
    async with factory() as session:
        stored_permit = await session.get(PermitModel, permit["permit_id"])
        first_reservation = await session.get(
            PermitCallReservationModel,
            first.record_id,
        )
        second_reservation = await session.get(
            PermitCallReservationModel,
            second.record_id,
        )
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1")
    assert first_reservation is not None
    assert first_reservation.state == "released"
    assert first_reservation.released_at is not None
    assert second_reservation is not None
    assert second_reservation.state == "reserved"


@pytest.mark.anyio
async def test_stale_uncharged_local_reservation_reconciles_for_safe_retry(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="local-stale-release",
        max_calls=1,
    )
    first, first_validation = await _reserve_constrained_local_call(
        suffix="local-stale-release-call",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert first_validation.allowed is True

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            record = await session.get(IdempotencyRecordModel, first.record_id)
            assert record is not None
            record.created_at = utc_now() - timedelta(hours=1)
            session.add(record)

    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=900
    )
    assert (repaired, needs_review) == (1, 0)

    async with factory() as session:
        stale_identity = await session.get(IdempotencyRecordModel, first.record_id)
        stale_reservation = await session.get(
            PermitCallReservationModel,
            first.record_id,
        )
    assert stale_identity is None
    assert stale_reservation is None

    replacement, replacement_validation = await _reserve_constrained_local_call(
        suffix="local-stale-release-call",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert replacement.record_id != first.record_id
    assert replacement_validation.allowed is True
    async with factory() as session:
        stored_permit = await session.get(PermitModel, permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1")


@pytest.mark.anyio
async def test_stale_charged_local_reservation_remains_counted_for_review(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="local-stale-charged",
        max_calls=1,
    )
    first, first_validation = await _reserve_constrained_local_call(
        suffix="local-stale-charged-call",
        provisioned=provisioned,
        permit=permit,
        tool_name=tool_name,
    )
    assert first_validation.allowed is True
    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.PLATFORM_FEE,
        units=Decimal("10"),
        request_path="/mcp/invoke",
        operation_key=first.record_id,
    )
    assert charge.entry_id

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            record = await session.get(IdempotencyRecordModel, first.record_id)
            assert record is not None
            record.created_at = utc_now() - timedelta(hours=1)
            session.add(record)

    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=900
    )
    assert (repaired, needs_review) == (0, 1)

    async with factory() as session:
        identity = await session.get(IdempotencyRecordModel, first.record_id)
        reservation = await session.get(PermitCallReservationModel, first.record_id)
        stored_permit = await session.get(PermitModel, permit["permit_id"])
    assert identity is not None
    assert identity.ledger_entry_id == charge.entry_id
    assert reservation is not None
    assert reservation.state == "reserved"
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1")


@pytest.mark.anyio
async def test_local_reservation_rejects_mismatched_idempotency_identity(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, tool_name = await _create_constrained_permit(
        client,
        suffix="local-identity",
        max_calls=1,
    )
    arguments = {"value": "local-identity"}
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key="invoke-local-identity",
        request_payload={"tool": tool_name, "arguments": arguments},
        operation_kind="local",
    )

    with pytest.raises(PermitError, match="permit_call_identity_invalid"):
        await get_permit_service().authorize_and_reserve(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            tool_name=tool_name,
            estimated_credits=Decimal("1"),
            key_id=provisioned["key_id"],
            arguments=arguments,
            idempotency_record_id=begun.record_id,
            request_hash="f" * 64,
        )

    attacker = await provision_agent_wallet(client)
    with pytest.raises(PermitError, match="permit_call_identity_invalid"):
        await get_permit_service().authorize_and_reserve(
            permit_id=permit["permit_id"],
            wallet_id=attacker["agent_wallet_id"],
            tool_name=tool_name,
            estimated_credits=Decimal("1"),
            key_id=attacker["key_id"],
            arguments=arguments,
            idempotency_record_id=begun.record_id,
            request_hash=begun.request_hash,
        )

    factory = get_session_factory()
    async with factory() as session:
        stored_permit = await session.get(PermitModel, permit["permit_id"])
        reservation = await session.get(PermitCallReservationModel, begun.record_id)
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")
    assert reservation is None


@pytest.mark.anyio
async def test_operation_key_rejects_changed_debit_and_cross_wallet_identity(
    client: AsyncClient,
    clean_database,
) -> None:
    wallet_a, _permit, _payload, begun = await _seed_governed_identity(
        client,
        suffix="debit-conflict-a",
    )
    wallet_b = await provision_agent_wallet(client)
    money = get_agent_money()

    await money.charge(
        wallet_id=wallet_a["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )
    with pytest.raises(LedgerOperationConflictError):
        await money.charge(
            wallet_id=wallet_a["agent_wallet_id"],
            service_category=ServiceCategory.AGENT_COMMS,
            units=Decimal("2"),
            request_path="/mcp/messages",
            operation_key=begun.record_id,
        )
    with pytest.raises(ValueError, match="ledger_operation_record_not_found"):
        await money.charge(
            wallet_id=wallet_b["agent_wallet_id"],
            service_category=ServiceCategory.AGENT_COMMS,
            units=Decimal("1"),
            request_path="/mcp/messages",
            operation_key=begun.record_id,
        )

    factory = get_session_factory()
    async with factory() as session:
        other_wallet = await session.get(WalletModel, wallet_b["agent_wallet_id"])
    assert other_wallet is not None
    assert other_wallet.balance == Decimal("1000")
    assert other_wallet.hourly_spent == Decimal("0")


@pytest.mark.anyio
async def test_operation_key_rejects_tampered_idempotency_checkpoint(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, _permit, _payload, begun = await _seed_governed_identity(
        client,
        suffix="debit-checkpoint-conflict",
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            record = await session.get(IdempotencyRecordModel, begun.record_id)
            assert record is not None
            record.ledger_entry_id = "tampered-ledger-entry"
            session.add(record)

    with pytest.raises(
        LedgerOperationConflictError,
        match="ledger_operation_checkpoint_conflict",
    ):
        await get_agent_money().charge(
            wallet_id=provisioned["agent_wallet_id"],
            service_category=ServiceCategory.AGENT_COMMS,
            units=Decimal("1"),
            request_path="/mcp/messages",
            operation_key=begun.record_id,
        )

    async with factory() as session:
        wallet = await session.get(WalletModel, provisioned["agent_wallet_id"])
        debit_count = await session.scalar(
            select(func.count())
            .select_from(LedgerEntryModel)
            .where(LedgerEntryModel.operation_key == begun.record_id)
        )
    assert wallet is not None and wallet.balance == Decimal("1000")
    assert debit_count == 0


@pytest.mark.anyio
async def test_receipt_idempotency_recovers_lost_ack_and_checks_invariants(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioned, permit, request_payload, begun = await _seed_governed_identity(
        client,
        suffix="receipt-ack",
    )
    service = get_receipt_service()
    original_refresh = AsyncSession.refresh
    refresh_failed = False

    async def lose_first_receipt_ack(self, instance, *args, **kwargs):  # noqa: ANN001
        nonlocal refresh_failed
        if isinstance(instance, ReceiptModel) and not refresh_failed:
            refresh_failed = True
            raise RuntimeError("simulated_commit_ack_loss")
        return await original_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "refresh", lose_first_receipt_ack)
    receipt = await service.create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="partner-tool-receipt-ack",
        request_payload=request_payload,
        response_payload={"ok": True},
        ledger_entry_id=None,
        credits_authorized=Decimal("1.5"),
        credits_charged=Decimal("0"),
        outcome="denied",
        audit_event_id=None,
        idempotency_record_id=begun.record_id,
    )
    replay = await service.create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="partner-tool-receipt-ack",
        request_payload=None,
        request_hash=begun.request_hash,
        response_payload={"ok": True},
        ledger_entry_id=None,
        credits_authorized=Decimal("1.5"),
        credits_charged=Decimal("0"),
        outcome="denied",
        audit_event_id=None,
        idempotency_record_id=begun.record_id,
    )
    assert refresh_failed is True
    assert replay.receipt_id == receipt.receipt_id
    assert replay.idempotency_record_id == begun.record_id
    assert (await service.verify_receipt(receipt.receipt_id))[0] is True

    with pytest.raises(ReceiptError, match="receipt_idempotency_conflict"):
        await service.create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="different-tool",
            request_payload=request_payload,
            response_payload={"ok": True},
            ledger_entry_id=None,
            credits_authorized=Decimal("1.5"),
            credits_charged=Decimal("0"),
            outcome="denied",
            audit_event_id=None,
            idempotency_record_id=begun.record_id,
        )

    factory = get_session_factory()
    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ReceiptModel)
            .where(ReceiptModel.idempotency_record_id == begun.record_id)
        )
    assert count == 1


@pytest.mark.anyio
async def test_receipt_verification_accepts_unambiguous_historical_link_backfill(
    client: AsyncClient,
    clean_database,
) -> None:
    (
        _provisioned,
        _permit,
        _payload,
        _begun,
        receipt_model,
    ) = await _seed_backfilled_legacy_receipt(
        client,
        suffix="legacy-receipt-positive",
    )

    valid, reason, verified = await get_receipt_service().verify_receipt(
        receipt_model.receipt_id
    )

    assert valid is True
    assert reason is None
    assert verified is not None
    assert verified.idempotency_record_id == receipt_model.idempotency_record_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    "invalid_linkage",
    [
        "missing_response_reference",
        "record_id_mismatch",
        "wallet_mismatch",
        "request_hash_mismatch",
        "ambiguous_response_reference",
        "signed_field_tamper",
        "dispatch_link_present",
    ],
)
async def test_receipt_verification_rejects_unsafe_historical_link_fallback(
    client: AsyncClient,
    clean_database,
    invalid_linkage: str,
) -> None:
    (
        provisioned,
        _permit,
        request_payload,
        begun,
        receipt_model,
    ) = await _seed_backfilled_legacy_receipt(
        client,
        suffix=f"legacy-receipt-{invalid_linkage}",
    )
    idempotency = get_idempotency_service()
    factory = get_session_factory()

    if invalid_linkage == "dispatch_link_present":
        # No DB write is needed: the fallback must be rejected before querying
        # linkage because historical receipts never carried a dispatch link.
        receipt_model.dispatch_attempt_id = "dsp-untrusted-link"
        assert await get_receipt_service().verify_model(receipt_model) is False
        return

    other_record: IdempotencyBegin | None = None
    if invalid_linkage in {"record_id_mismatch", "ambiguous_response_reference"}:
        other_record = await idempotency.begin_with_record(
            wallet_id=provisioned["agent_wallet_id"],
            endpoint="/mcp/messages",
            idempotency_key=f"invoke-{invalid_linkage}-other",
            request_payload=request_payload,
        )
        assert other_record.replay is None

    other_wallet: dict | None = None
    if invalid_linkage == "wallet_mismatch":
        other_wallet = await provision_agent_wallet(client)

    async with factory() as session:
        stored_receipt = await session.get(ReceiptModel, receipt_model.receipt_id)
        record = await session.get(IdempotencyRecordModel, begun.record_id)
        assert stored_receipt is not None
        assert record is not None

        if invalid_linkage == "missing_response_reference":
            record.response_reference = None
        elif invalid_linkage == "record_id_mismatch":
            assert other_record is not None
            stored_receipt.idempotency_record_id = other_record.record_id
        elif invalid_linkage == "wallet_mismatch":
            assert other_wallet is not None
            record.wallet_id = other_wallet["agent_wallet_id"]
        elif invalid_linkage == "request_hash_mismatch":
            record.request_hash = "f" * 64
        elif invalid_linkage == "ambiguous_response_reference":
            assert other_record is not None
            second = await session.get(IdempotencyRecordModel, other_record.record_id)
            assert second is not None
            second.response_reference = stored_receipt.receipt_id
            session.add(second)
        elif invalid_linkage == "signed_field_tamper":
            stored_receipt.outcome = "success"

        session.add(record)
        session.add(stored_receipt)
        await session.commit()

    valid, reason, _verified = await get_receipt_service().verify_receipt(
        receipt_model.receipt_id
    )
    assert valid is False
    assert reason == "receipt_signature_invalid"


@pytest.mark.anyio
async def test_receipt_reconciler_hash_path_is_strict(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="receipt-hash",
    )
    service = get_receipt_service()
    receipt = await service.create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="partner-tool-receipt-hash",
        request_payload=None,
        request_hash=begun.request_hash,
        response_payload={"error": "delivery_uncertain"},
        ledger_entry_id=None,
        credits_authorized=Decimal("1.5"),
        credits_charged=Decimal("0"),
        outcome="delivery_uncertain",
        audit_event_id=None,
        idempotency_record_id=begun.record_id,
    )
    assert receipt.request_hash == begun.request_hash
    with pytest.raises(ReceiptError, match="receipt_request_identity_invalid"):
        await service.create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="partner-tool-receipt-hash",
            request_payload={},
            request_hash=begun.request_hash,
            response_payload=None,
            ledger_entry_id=None,
            credits_authorized=Decimal("1.5"),
            credits_charged=Decimal("0"),
            outcome="delivery_uncertain",
            audit_event_id=None,
        )
    with pytest.raises(ReceiptError, match="receipt_request_hash_invalid"):
        await service.create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="partner-tool-receipt-hash",
            request_payload=None,
            request_hash="not-a-hash",
            response_payload=None,
            ledger_entry_id=None,
            credits_authorized=Decimal("1.5"),
            credits_charged=Decimal("0"),
            outcome="delivery_uncertain",
            audit_event_id=None,
        )
    with pytest.raises(ReceiptError, match="receipt_response_hash_mismatch"):
        await service.create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="partner-tool-receipt-hash",
            request_payload=None,
            request_hash=begun.request_hash,
            response_payload={"message": "伙伴响应"},
            response_hash_override="0" * 64,
            ledger_entry_id=None,
            credits_authorized=Decimal("1.5"),
            credits_charged=Decimal("0"),
            outcome="delivery_uncertain",
            audit_event_id=None,
            dispatch_attempt_id="attempt-invalid-response-hash",
        )


@pytest.mark.anyio
async def test_dispatch_attempt_state_machine_and_bounded_result(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="dispatch-state",
    )
    wallet_id = provisioned["agent_wallet_id"]
    service = get_mcp_dispatch_attempt_service()
    prepared = await service.prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=wallet_id,
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id="partner-tool-dispatch-state",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
    )
    duplicate = await service.prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=wallet_id,
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id="partner-tool-dispatch-state",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
    )
    assert duplicate.attempt_id == prepared.attempt_id
    with pytest.raises(DispatchAttemptConflictError):
        await service.prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=wallet_id,
            permit_id=permit["permit_id"],
            key_id=provisioned["key_id"],
            public_tool_id="different-public-tool",
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
        )

    charge = await get_agent_money().charge(
        wallet_id=wallet_id,
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path="/mcp/messages",
        operation_key=begun.record_id,
    )
    attached = await service.attach_charge(
        attempt_id=prepared.attempt_id,
        ledger_entry_id=charge.entry_id,  # type: ignore[union-attr]
        credits_charged=Decimal("1.5"),
    )
    assert attached.ledger_entry_id == charge.entry_id  # type: ignore[union-attr]
    dispatched = await service.claim_dispatch(prepared.attempt_id)
    assert dispatched.state == "dispatch_claimed"
    assert dispatched.dispatch_claim_hash is not None
    assert len(dispatched.dispatch_claim_hash) == 64
    with pytest.raises(
        DispatchClaimUnavailableError,
        match="dispatch_claim_unavailable",
    ):
        await service.claim_dispatch(prepared.attempt_id)

    with pytest.raises(DispatchResultTooLargeError):
        await service.complete(
            attempt_id=prepared.attempt_id,
            state="succeeded",
            result_payload={"content": "too large"},
            error_code=None,
            max_result_bytes=5,
        )
    context = await service.get_context(prepared.attempt_id)
    assert context is not None
    assert context.attempt.state == "dispatch_claimed"
    assert context.endpoint == "/mcp/messages"
    assert context.idempotency_key == "invoke-dispatch-state"

    rejected = await service.complete(
        attempt_id=prepared.attempt_id,
        state="response_rejected",
        result_payload=None,
        error_code="response_too_large",
        max_result_bytes=5,
    )
    assert rejected.state == "response_rejected"
    assert rejected.result_json is None
    with pytest.raises(
        DispatchAttemptConflictError,
        match="dispatch_transition_terminal",
    ):
        await service.claim_dispatch(prepared.attempt_id)
    with pytest.raises(DispatchAttemptConflictError):
        await service.complete(
            attempt_id=prepared.attempt_id,
            state="delivery_uncertain",
            result_payload=None,
            error_code="timeout",
            max_result_bytes=1024,
        )


@pytest.mark.anyio
async def test_dispatch_claim_recovers_lost_commit_ack_but_cannot_be_reacquired(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, attempt = await _seed_charged_dispatch_attempt(
        client,
        suffix="dispatch-claim-lost-ack",
    )
    original_exit = AsyncSessionTransaction.__aexit__
    acknowledgement_lost = False

    async def lose_commit_ack(self, exc_type, exc, tb):  # noqa: ANN001
        nonlocal acknowledgement_lost
        result = await original_exit(self, exc_type, exc, tb)
        if exc_type is None and not acknowledgement_lost:
            acknowledgement_lost = True
            raise RuntimeError("simulated_dispatch_claim_commit_ack_loss")
        return result

    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", lose_commit_ack)

    claimed = await service.claim_dispatch(attempt.attempt_id)

    assert acknowledgement_lost is True
    assert claimed.state == "dispatch_claimed"
    assert claimed.dispatch_claim_hash is not None
    with pytest.raises(
        DispatchClaimUnavailableError,
        match="dispatch_claim_unavailable",
    ):
        await service.claim_dispatch(attempt.attempt_id)


@pytest.mark.anyio
async def test_legacy_dispatched_attempt_without_claim_fails_closed(
    client: AsyncClient,
    clean_database,
) -> None:
    service, attempt = await _seed_charged_dispatch_attempt(
        client,
        suffix="dispatch-claim-legacy",
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            stored = await session.get(
                McpDispatchAttemptModel,
                attempt.attempt_id,
                with_for_update=True,
            )
            assert stored is not None
            stored.state = "dispatched"
            stored.dispatched_at = utc_now()
            stored.dispatch_claim_hash = None
            session.add(stored)

    with pytest.raises(
        DispatchClaimUnavailableError,
        match="dispatch_claim_unavailable",
    ):
        await service.claim_dispatch(attempt.attempt_id)

    context = await service.get_context(attempt.attempt_id)
    assert context is not None
    assert context.attempt.state == "dispatched"
    assert context.attempt.dispatch_claim_hash is None


@pytest.mark.anyio
async def test_prepared_attempt_with_dispatch_evidence_fails_closed(
    client: AsyncClient,
    clean_database,
) -> None:
    service, attempt = await _seed_charged_dispatch_attempt(
        client,
        suffix="dispatch-evidence-corrupt",
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            stored = await session.get(
                McpDispatchAttemptModel,
                attempt.attempt_id,
                with_for_update=True,
            )
            assert stored is not None
            stored.dispatched_at = utc_now()
            stored.updated_at = utc_now()
            session.add(stored)

    corrupted = await service.get_context(attempt.attempt_id)
    assert corrupted is not None
    with pytest.raises(
        DispatchClaimUnavailableError,
        match="dispatch_claim_unavailable",
    ):
        await service.claim_dispatch(attempt.attempt_id)
    with pytest.raises(
        DispatchClaimUnavailableError,
        match="dispatch_claim_unavailable",
    ):
        await service.complete_pre_dispatch_failure(
            attempt_id=attempt.attempt_id,
            expected_updated_at=corrupted.attempt.updated_at,
            ledger_entry_id=corrupted.attempt.ledger_entry_id,
            credits_charged=corrupted.attempt.credits_charged,
            result_payload={"error": "failed_refunded"},
            error_code="upstream_pre_dispatch_failed",
            max_result_bytes=1024,
        )

    after = await service.get_context(attempt.attempt_id)
    assert after is not None
    assert after.attempt.state == "prepared"
    assert after.attempt.completed_at is None
    assert after.attempt.debit_refunded_at is None
    assert after.attempt.budget_released_at is None


@pytest.mark.anyio
async def test_remote_reservation_and_prepared_attempt_are_atomic_and_idempotent(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="atomic-prepare",
    )
    service = get_mcp_dispatch_attempt_service()
    kwargs = {
        "idempotency_record_id": begun.record_id,
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
        "key_id": provisioned["key_id"],
        "public_tool_id": "partner-tool-atomic-prepare",
        "upstream_tool_name": "remote_tool",
        "upstream_origin": "https://partner.example",
        "request_hash": begun.request_hash,
        "credits_authorized": Decimal("1.5"),
    }

    validation, prepared = await service.authorize_reserve_and_prepare(**kwargs)
    assert validation.allowed is True
    assert prepared is not None and prepared.state == "prepared"
    replay_validation, replayed = await service.authorize_reserve_and_prepare(**kwargs)
    assert replay_validation.allowed is True
    assert replayed is not None and replayed.attempt_id == prepared.attempt_id
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1.5")


@pytest.mark.anyio
async def test_remote_prepare_rejects_missing_required_human_approval(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="approval-required",
        requires_human_approval=True,
    )

    with pytest.raises(
        DispatchAttemptConflictError,
        match="dispatch_approval_required",
    ):
        await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            key_id=provisioned["key_id"],
            public_tool_id="partner-tool-approval-required",
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
        )

    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")
    factory = get_session_factory()
    async with factory() as session:
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    assert int(attempt_count or 0) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "approval_status", "wrong_tool", "wrong_wallet"),
    [
        ("missing-row", None, False, False),
        ("wrong-tool", "approved", True, False),
        ("wrong-request", "approved", False, False),
        ("cross-wallet", "approved", False, True),
        ("rejected", "rejected", False, False),
        ("missing-decision", "approved", False, False),
        ("decision-before-request", "approved", False, False),
        ("decision-at-deadline", "approved", False, False),
        ("decision-after-deadline", "approved", False, False),
    ],
)
async def test_remote_prepare_rejects_invalid_human_approval_binding(
    client: AsyncClient,
    clean_database,
    case: str,
    approval_status: str | None,
    wrong_tool: bool,
    wrong_wallet: bool,
) -> None:
    suffix = f"approval-{case}"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    provisioned, permit, request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = f"appr-{case}"
    if approval_status is not None:
        await _store_human_approval(
            approval_id=approval_id,
            wallet_id=(
                provisioned["sponsor_wallet_id"]
                if wrong_wallet
                else provisioned["agent_wallet_id"]
            ),
            permit_id=permit["permit_id"],
            tool_name="wrong-tool" if wrong_tool else tool_name,
            idempotency_key=idempotency_key,
            status=approval_status,
            request_hash=(
                "a" * 64
                if case == "wrong-request"
                else invoke_request_hash(
                    tool_name,
                    request_payload["arguments"],
                    Decimal("1.5"),
                )
            ),
        )
        if case.startswith("decision-") or case == "missing-decision":
            factory = get_session_factory()
            async with factory() as session:
                async with session.begin():
                    approval = await session.get(HumanApprovalModel, approval_id)
                    assert approval is not None
                    if case == "missing-decision":
                        approval.decided_at = None
                    elif case == "decision-before-request":
                        approval.decided_at = approval.requested_at - timedelta(
                            seconds=1
                        )
                    elif case == "decision-at-deadline":
                        approval.decided_at = approval.expires_at
                    else:
                        approval.decided_at = approval.expires_at + timedelta(seconds=1)
                    session.add(approval)

    with pytest.raises(
        DispatchAttemptConflictError,
        match="dispatch_approval_linkage_invalid",
    ):
        await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            approval_id=approval_id,
            key_id=provisioned["key_id"],
            public_tool_id=tool_name,
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
            arguments=request_payload["arguments"],
        )

    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")
    factory = get_session_factory()
    async with factory() as session:
        approval = (
            await session.get(HumanApprovalModel, approval_id)
            if approval_status is not None
            else None
        )
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    if approval_status == "approved":
        assert approval is not None and approval.status == "approved"
    assert int(attempt_count or 0) == 0


@pytest.mark.anyio
async def test_remote_prepare_rejects_consumed_approval_without_attempt(
    client: AsyncClient,
    clean_database,
) -> None:
    suffix = "approval-consumed"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    provisioned, permit, request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = "appr-valid-consumed"
    await _store_human_approval(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        request_hash=invoke_request_hash(
            tool_name,
            request_payload["arguments"],
            Decimal("1.5"),
        ),
    )

    with pytest.raises(
        DispatchAttemptConflictError,
        match="dispatch_approval_atomic_prepare_required",
    ):
        await get_mcp_dispatch_attempt_service().prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            approval_id=approval_id,
            key_id=provisioned["key_id"],
            public_tool_id=tool_name,
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
        )

    with pytest.raises(
        DispatchAttemptConflictError,
        match="dispatch_approval_linkage_invalid",
    ):
        await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            approval_id=approval_id,
            key_id=provisioned["key_id"],
            public_tool_id=tool_name,
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
            arguments=request_payload["arguments"],
        )

    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")
    factory = get_session_factory()
    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    assert approval is not None and approval.status == "consumed"
    assert int(attempt_count or 0) == 0


@pytest.mark.anyio
async def test_remote_prepare_atomically_consumes_approved_human_approval(
    client: AsyncClient,
    clean_database,
) -> None:
    suffix = "approval-atomic-consume"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = "appr-atomic-consume"
    await _store_human_approval(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status="approved",
        request_hash=invoke_request_hash(
            tool_name,
            {"value": suffix},
            Decimal("1.5"),
        ),
    )

    (
        validation,
        attempt,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        approval_id=approval_id,
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
        arguments={"value": suffix},
    )

    assert validation.allowed is True
    assert attempt is not None and attempt.approval_id == approval_id
    (
        replay_validation,
        replayed,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        approval_id=approval_id,
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
        arguments={"value": suffix},
    )
    assert replay_validation.allowed is True
    assert replayed is not None and replayed.attempt_id == attempt.attempt_id
    factory = get_session_factory()
    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
    assert approval is not None and approval.status == "consumed"
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1.5")


@pytest.mark.anyio
async def test_remote_prepare_failure_rolls_back_human_approval_consumption(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = "approval-atomic-rollback"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = "appr-atomic-rollback"
    await _store_human_approval(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status="approved",
        request_hash=invoke_request_hash(
            tool_name,
            {"value": suffix},
            Decimal("1.5"),
        ),
    )
    original_flush = AsyncSession.flush

    async def fail_attempt_flush(self, objects=None):  # noqa: ANN001
        if any(isinstance(row, McpDispatchAttemptModel) for row in self.new):
            raise RuntimeError("simulated_prepare_write_failure")
        return await original_flush(self, objects)

    monkeypatch.setattr(AsyncSession, "flush", fail_attempt_flush)
    with pytest.raises(
        DispatchPrepareRolledBackError,
        match="dispatch_prepare_rolled_back",
    ):
        await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            approval_id=approval_id,
            key_id=provisioned["key_id"],
            public_tool_id=tool_name,
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
            arguments={"value": suffix},
        )

    factory = get_session_factory()
    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    assert approval is not None and approval.status == "approved"
    assert int(attempt_count or 0) == 0
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")


@pytest.mark.anyio
async def test_remote_prepare_consumes_predeadline_approval_after_deadline(
    client: AsyncClient,
    clean_database,
) -> None:
    suffix = "approval-expired-before-prepare"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    credits = Decimal("1.5")
    arguments = {"value": suffix}
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = "appr-expired-before-prepare"
    await _store_human_approval(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status="approved",
        request_hash=invoke_request_hash(tool_name, arguments, credits),
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            approval = await session.get(HumanApprovalModel, approval_id)
            assert approval is not None
            now = utc_now()
            approval.requested_at = now - timedelta(seconds=10)
            approval.decided_at = now - timedelta(seconds=8)
            approval.expires_at = now - timedelta(seconds=1)
            session.add(approval)

    (
        validation,
        attempt,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        approval_id=approval_id,
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=credits,
        arguments=arguments,
    )

    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
        attempts = (
            (
                await session.execute(
                    select(McpDispatchAttemptModel).where(
                        McpDispatchAttemptModel.idempotency_record_id == begun.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert validation.allowed is True
    assert attempt is not None
    assert approval is not None and approval.status == "consumed"
    assert [stored.attempt_id for stored in attempts] == [attempt.attempt_id]
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == credits


@pytest.mark.anyio
@pytest.mark.parametrize("denial_case", ["budget", "wrong-key", "revoked"])
async def test_remote_permit_denial_does_not_consume_human_approval(
    client: AsyncClient,
    clean_database,
    denial_case: str,
) -> None:
    suffix = f"approval-permit-denied-{denial_case}"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    credits = Decimal("1000000") if denial_case == "budget" else Decimal("1.5")
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = "appr-permit-denied"
    await _store_human_approval(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status="approved",
        request_hash=invoke_request_hash(
            tool_name,
            {"value": suffix},
            credits,
        ),
    )
    if denial_case == "revoked":
        await get_permit_service().revoke_permit(permit["permit_id"])

    (
        validation,
        attempt,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        approval_id=approval_id,
        key_id=(
            "key-not-bound-to-permit"
            if denial_case == "wrong-key"
            else provisioned["key_id"]
        ),
        public_tool_id=tool_name,
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=credits,
        arguments={"value": suffix},
    )

    assert validation.allowed is False
    assert attempt is None
    factory = get_session_factory()
    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
    assert approval is not None and approval.status == "approved"
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")


@pytest.mark.anyio
async def test_remote_prepare_failure_rolls_back_budget_and_attempt(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="atomic-prepare-rollback",
    )
    original_flush = AsyncSession.flush

    async def fail_attempt_flush(self, objects=None):  # noqa: ANN001
        if any(isinstance(row, McpDispatchAttemptModel) for row in self.new):
            raise RuntimeError("simulated_prepare_write_failure")
        return await original_flush(self, objects)

    monkeypatch.setattr(AsyncSession, "flush", fail_attempt_flush)
    service = get_mcp_dispatch_attempt_service()
    with pytest.raises(
        DispatchPrepareRolledBackError,
        match="dispatch_prepare_rolled_back",
    ):
        await service.authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            key_id=provisioned["key_id"],
            public_tool_id="partner-tool-atomic-prepare-rollback",
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
        )

    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")
    factory = get_session_factory()
    async with factory() as session:
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    assert int(attempt_count or 0) == 0


@pytest.mark.anyio
async def test_remote_prepare_recovery_read_failure_is_commit_uncertain(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="atomic-prepare-recovery-unavailable",
    )
    original_flush = AsyncSession.flush
    service = get_mcp_dispatch_attempt_service()
    original_lookup = service._get_by_idempotency_record
    lookup_count = 0

    async def fail_attempt_flush(self, objects=None):  # noqa: ANN001
        if any(isinstance(row, McpDispatchAttemptModel) for row in self.new):
            raise RuntimeError("simulated_prepare_write_failure")
        return await original_flush(self, objects)

    async def fail_recovery_lookup(session, record_id):  # noqa: ANN001
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return await original_lookup(session, record_id)
        raise RuntimeError("simulated_recovery_read_failure")

    monkeypatch.setattr(AsyncSession, "flush", fail_attempt_flush)
    monkeypatch.setattr(service, "_get_by_idempotency_record", fail_recovery_lookup)

    with pytest.raises(
        DispatchPrepareCommitUncertainError,
        match="dispatch_prepare_commit_uncertain",
    ):
        await service.authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            key_id=provisioned["key_id"],
            public_tool_id="partner-tool-atomic-prepare-recovery-unavailable",
            upstream_tool_name="remote_tool",
            upstream_origin="https://partner.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("1.5"),
        )

    assert lookup_count == 2
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("0")
    factory = get_session_factory()
    async with factory() as session:
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    assert int(attempt_count or 0) == 0


@pytest.mark.anyio
async def test_remote_prepare_recovers_lost_commit_ack_without_double_reserving(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="atomic-prepare-lost-ack",
        requires_human_approval=True,
    )
    approval_id = "appr-atomic-prepare-lost-ack"
    arguments = {"value": "atomic-prepare-lost-ack"}
    await _store_human_approval(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name="partner-tool-atomic-prepare-lost-ack",
        idempotency_key="invoke-atomic-prepare-lost-ack",
        status="approved",
        request_hash=invoke_request_hash(
            "partner-tool-atomic-prepare-lost-ack",
            arguments,
            Decimal("1.5"),
        ),
    )
    original_exit = AsyncSessionTransaction.__aexit__
    acknowledgement_lost = False

    async def lose_first_commit_ack(self, exc_type, exc, tb):  # noqa: ANN001
        nonlocal acknowledgement_lost
        result = await original_exit(self, exc_type, exc, tb)
        if exc_type is None and not acknowledgement_lost:
            acknowledgement_lost = True
            raise RuntimeError("simulated_prepare_commit_ack_loss")
        return result

    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", lose_first_commit_ack)
    (
        validation,
        attempt,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        approval_id=approval_id,
        key_id=provisioned["key_id"],
        public_tool_id="partner-tool-atomic-prepare-lost-ack",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
        arguments=arguments,
    )

    assert acknowledgement_lost is True
    assert validation.allowed is True
    assert attempt is not None and attempt.state == "prepared"
    assert attempt.approval_id == approval_id
    (
        replay_validation,
        replayed,
    ) = await get_mcp_dispatch_attempt_service().authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        approval_id=approval_id,
        key_id=provisioned["key_id"],
        public_tool_id="partner-tool-atomic-prepare-lost-ack",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
        arguments=arguments,
    )
    assert replay_validation.allowed is True
    assert replayed is not None and replayed.attempt_id == attempt.attempt_id
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1.5")
    factory = get_session_factory()
    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
    assert approval is not None and approval.status == "consumed"
    assert int(attempt_count or 0) == 1


@pytest.mark.anyio
async def test_dispatch_attempt_rejects_unsafe_origin_and_invalid_transition(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="dispatch-negative",
    )
    service = get_mcp_dispatch_attempt_service()
    kwargs = {
        "idempotency_record_id": begun.record_id,
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
        "key_id": provisioned["key_id"],
        "public_tool_id": "partner-tool-dispatch-negative",
        "upstream_tool_name": "remote_tool",
        "request_hash": begun.request_hash,
        "credits_authorized": Decimal("1.5"),
    }
    with pytest.raises(DispatchAttemptError, match="dispatch_upstream_origin_invalid"):
        await service.prepare(
            **kwargs,
            upstream_origin="https://secret:token@partner.example",
        )

    prepared = await service.prepare(
        **kwargs,
        upstream_origin="https://partner.example",
    )
    with pytest.raises(
        DispatchAttemptConflictError,
        match="dispatch_transition_invalid",
    ):
        await service.claim_dispatch(prepared.attempt_id)
    unclaimed = await service.get_context(prepared.attempt_id)
    assert unclaimed is not None
    assert unclaimed.attempt.state == "prepared"
    assert unclaimed.attempt.dispatch_claim_hash is None
    with pytest.raises(DispatchAttemptConflictError):
        await service.complete(
            attempt_id=prepared.attempt_id,
            state="succeeded",
            result_payload={"ok": True},
            error_code=None,
            max_result_bytes=1024,
        )

    failed = await service.complete_pre_dispatch_failure(
        attempt_id=prepared.attempt_id,
        expected_updated_at=unclaimed.attempt.updated_at,
        result_payload=None,
        error_code="connect_failed",
        max_result_bytes=1024,
    )
    assert failed.state == "returned_error"


@pytest.mark.anyio
async def test_dispatch_reconciliation_queries_active_and_unfinalized_terminal(
    client: AsyncClient,
    clean_database,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="dispatch-stale",
    )
    service = get_mcp_dispatch_attempt_service()
    prepared = await service.prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id="partner-tool-dispatch-stale",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
    )
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(McpDispatchAttemptModel, prepared.attempt_id)
        assert model is not None
        model.updated_at = utc_now() - timedelta(minutes=10)
        session.add(model)
        await session.commit()

    stale = await service.list_stale_contexts(idle_seconds=300)
    assert [item.attempt.attempt_id for item in stale] == [prepared.attempt_id]

    terminal = await service.complete_pre_dispatch_failure(
        attempt_id=prepared.attempt_id,
        expected_updated_at=stale[0].attempt.updated_at,
        result_payload=None,
        error_code="connect_failed",
        max_result_bytes=1024,
    )
    async with factory() as session:
        model = await session.get(McpDispatchAttemptModel, terminal.attempt_id)
        assert model is not None
        model.updated_at = utc_now() - timedelta(minutes=10)
        session.add(model)
        await session.commit()

    unfinalized = await service.list_unfinalized_terminal_contexts(idle_seconds=300)
    assert [item.attempt.attempt_id for item in unfinalized] == [prepared.attempt_id]
