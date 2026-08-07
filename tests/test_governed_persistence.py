from __future__ import annotations

from datetime import timedelta
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
    ReceiptModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.billing_engine import LedgerOperationConflictError
from app.services.idempotency import IdempotencyBegin, get_idempotency_service
from app.services.mcp_dispatch_attempts import (
    DispatchAttemptConflictError,
    DispatchAttemptError,
    DispatchResultTooLargeError,
    get_mcp_dispatch_attempt_service,
)
from app.services.permits import get_permit_service
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


async def _store_human_approval(
    *,
    approval_id: str,
    wallet_id: str,
    permit_id: str,
    tool_name: str,
    idempotency_key: str,
    status: str = "consumed",
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            HumanApprovalModel(
                approval_id=approval_id,
                wallet_id=wallet_id,
                permit_id=permit_id,
                tool=tool_name,
                idempotency_key=idempotency_key,
                request_hash="a" * 64,
                status=status,
                simulated=True,
                expires_at=utc_now() + timedelta(minutes=30),
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
    dispatched = await service.mark_dispatched(prepared.attempt_id)
    assert dispatched.state == "dispatched"

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
    assert context.attempt.state == "dispatched"
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
        await service.mark_dispatched(prepared.attempt_id)
    with pytest.raises(DispatchAttemptConflictError):
        await service.complete(
            attempt_id=prepared.attempt_id,
            state="delivery_uncertain",
            result_payload=None,
            error_code="timeout",
            max_result_bytes=1024,
        )


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
    ("case", "approval_status", "wrong_tool"),
    [
        ("missing-row", None, False),
        ("wrong-binding", "consumed", True),
        ("unconsumed", "approved", False),
    ],
)
async def test_remote_prepare_rejects_invalid_human_approval_binding(
    client: AsyncClient,
    clean_database,
    case: str,
    approval_status: str | None,
    wrong_tool: bool,
) -> None:
    suffix = f"approval-{case}"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix=suffix,
        requires_human_approval=True,
    )
    approval_id = f"appr-{case}"
    if approval_status is not None:
        await _store_human_approval(
            approval_id=approval_id,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            tool_name="wrong-tool" if wrong_tool else tool_name,
            idempotency_key=idempotency_key,
            status=approval_status,
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
async def test_remote_prepare_persists_valid_consumed_human_approval(
    client: AsyncClient,
    clean_database,
) -> None:
    suffix = "approval-consumed"
    tool_name = f"partner-tool-{suffix}"
    idempotency_key = f"invoke-{suffix}"
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
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
    )

    assert validation.allowed is True
    assert attempt is not None
    assert attempt.approval_id == approval_id
    context = await get_mcp_dispatch_attempt_service().get_context(attempt.attempt_id)
    assert context is not None
    assert context.attempt.approval_id == approval_id
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1.5")


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
    with pytest.raises(RuntimeError, match="simulated_prepare_write_failure"):
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
async def test_remote_prepare_recovers_lost_commit_ack_without_double_reserving(
    client: AsyncClient,
    clean_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioned, permit, _request_payload, begun = await _seed_governed_identity(
        client,
        suffix="atomic-prepare-lost-ack",
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
        key_id=provisioned["key_id"],
        public_tool_id="partner-tool-atomic-prepare-lost-ack",
        upstream_tool_name="remote_tool",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=Decimal("1.5"),
    )

    assert acknowledgement_lost is True
    assert validation.allowed is True
    assert attempt is not None and attempt.state == "prepared"
    stored_permit = await get_permit_service().get_permit(permit["permit_id"])
    assert stored_permit is not None
    assert stored_permit.spent_credits == Decimal("1.5")
    factory = get_session_factory()
    async with factory() as session:
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.idempotency_record_id == begun.record_id)
        )
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
    with pytest.raises(DispatchAttemptConflictError):
        await service.mark_dispatched(prepared.attempt_id)
    with pytest.raises(DispatchAttemptConflictError):
        await service.complete(
            attempt_id=prepared.attempt_id,
            state="succeeded",
            result_payload={"ok": True},
            error_code=None,
            max_result_bytes=1024,
        )

    failed = await service.complete(
        attempt_id=prepared.attempt_id,
        state="returned_error",
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

    terminal = await service.complete(
        attempt_id=prepared.attempt_id,
        state="returned_error",
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
