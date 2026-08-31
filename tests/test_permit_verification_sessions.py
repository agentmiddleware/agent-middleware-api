from __future__ import annotations

# Imported pytest fixtures intentionally share test parameter names.
# ruff: noqa: F811

import asyncio
import base64
import json
import os
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.time import utc_now
from app.db.database import get_engine, get_session_factory
from app.db.models import (
    HumanApprovalModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    PermitCallReservationModel,
    PermitModel,
    ReceiptModel,
    SigningKeyModel,
    WalletModel,
)
from app.main import app
from app.services import receipts, signing_keys
from app.services.permits import get_permit_service
from app.services.refund_reconciliation import (
    RefundReconciliationError,
    RefundReconciliationService,
)
from app.services.signing_keys import (
    SigningKeyError,
    canonical_json,
    sha256_hex,
)
from tests.test_permit_postgres_concurrency import (
    SeededPermit,
    SeededRefundReconciliation,
    seeded_permit as seeded_permit,
    seeded_refund_reconciliation as seeded_refund_reconciliation,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture(autouse=True)
def _isolate_verification_cases(clean_database):
    """Clean before imported seed fixtures create or remove shared signing keys."""


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as transport:
        yield transport


async def _seed_permit(client: AsyncClient) -> tuple[dict, dict]:
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="session-verification-tool",
        max_calls_per_tool={"session-verification-tool": 10},
    )
    return provisioned, permit


def _reject_nested_session():
    raise AssertionError("verification attempted a nested database session")


def _require_application_pool_one():
    engine = get_engine()
    settings = get_settings()
    if engine is None or engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL to prove application connection-pool progress")
    if os.environ.get(
        "RUN_POSTGRES_CONCURRENCY_TESTS"
    ) != "1" or settings.ENVIRONMENT not in {"test", "testing"}:
        pytest.skip("requires explicit opt-in to an isolated PostgreSQL test database")
    if settings.DB_POOL_SIZE != 1 or settings.DB_MAX_OVERFLOW != 0:
        pytest.skip(
            "set DB_POOL_SIZE=1 DB_MAX_OVERFLOW=0 before importing the application"
        )
    assert engine.pool.size() == 1
    assert engine.pool._max_overflow == 0
    return get_session_factory()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case", ["valid", "tampered", "malformed", "disabled", "missing"]
)
async def test_permit_verification_borrows_session_and_fails_closed(
    client, clean_database, monkeypatch, case
):
    provisioned, permit = await _seed_permit(client)
    factory = get_session_factory()
    service = get_permit_service()
    async with factory() as session:
        model = await session.get(PermitModel, permit["permit_id"])
        wallet = await session.get(WalletModel, provisioned["agent_wallet_id"])
        assert model is not None and wallet is not None
        key = await session.get(SigningKeyModel, model.key_id)
        assert key is not None and key.status == "active"
        original_balance = wallet.balance
        wallet.balance -= Decimal("1")
        await session.flush()

        if case == "tampered":
            model.max_credits += Decimal("1")
        elif case == "malformed":
            model.signature = "not-base64!"
        elif case == "disabled":
            # Leave the ORM identity map stale while the transaction's actual
            # key row is disabled. Verification must refresh the stored status.
            await session.execute(
                update(SigningKeyModel)
                .where(SigningKeyModel.key_id == key.key_id)
                .values(status="disabled")
                .execution_options(synchronize_session=False)
            )
            assert key.status == "active"
        elif case == "missing":
            model.key_id = "missing-verification-key"

        transaction = session.get_transaction()
        assert transaction is not None
        commit = AsyncMock(
            side_effect=AssertionError("reader committed caller session")
        )
        close = AsyncMock(side_effect=AssertionError("reader closed caller session"))
        with monkeypatch.context() as patch:
            patch.setattr(signing_keys, "get_session_factory", _reject_nested_session)
            patch.setattr(session, "commit", commit)
            patch.setattr(session, "close", close)
            assert await service.verify_signature(model, session=session) is (
                case == "valid"
            )
            validation = await service._validate_model_for_action(
                session=session,
                model=model,
                wallet_id=wallet.wallet_id,
                tool_name="session-verification-tool",
                estimated_credits=Decimal("1"),
                key_id=provisioned["key_id"],
            )
            replay = await service._validate_replay_model_access(
                session=session,
                model=model,
                wallet_id=wallet.wallet_id,
                key_id=provisioned["key_id"],
            )
            assert validation.allowed is (case == "valid")
            assert replay.allowed is (case == "valid")
            if case != "valid":
                assert validation.reason == "permit_signature_invalid"
                assert replay.reason == "permit_signature_invalid"
            if case == "disabled":
                assert key.status == "disabled"
            assert transaction.is_active
            commit.assert_not_awaited()
            close.assert_not_awaited()
        await session.rollback()

    async with factory() as session:
        wallet = await session.get(WalletModel, provisioned["agent_wallet_id"])
        assert wallet is not None and wallet.balance == original_balance


@pytest.mark.anyio
async def test_permit_verification_without_caller_session_remains_supported(
    client, clean_database
):
    _, permit = await _seed_permit(client)
    async with get_session_factory()() as session:
        model = await session.get(PermitModel, permit["permit_id"])
    assert model is not None
    assert await get_permit_service().verify_signature(model)


@pytest.mark.anyio
async def test_permit_validation_and_replay_complete_with_one_postgres_connection(
    client, clean_database
):
    factory = _require_application_pool_one()

    provisioned, permit = await _seed_permit(client)
    wallet_id = provisioned["agent_wallet_id"]
    record_id = "idm-single-connection-verification"
    request_hash = sha256_hex({"tool": "session-verification-tool"})
    async with get_session_factory()() as session:
        session.add(
            IdempotencyRecordModel(
                record_id=record_id,
                wallet_id=wallet_id,
                endpoint="/mcp/invoke",
                idempotency_key="single-connection-verification",
                request_hash=request_hash,
                operation_kind="local",
            )
        )
        await session.commit()

    service = get_permit_service()
    action = {
        "permit_id": permit["permit_id"],
        "wallet_id": wallet_id,
        "tool_name": "session-verification-tool",
        "estimated_credits": Decimal("1"),
        "key_id": provisioned["key_id"],
    }

    async def validate_reserve_and_replay():
        assert (await service.validate_for_action(**action)).allowed
        reserved = await service.authorize_and_reserve(
            **action,
            idempotency_record_id=record_id,
            request_hash=request_hash,
        )
        assert reserved.allowed
        replayed = await service.authorize_and_reserve(
            **action,
            idempotency_record_id=record_id,
            request_hash=request_hash,
        )
        assert replayed.allowed
        assert (
            await service.validate_replay_access(
                permit_id=permit["permit_id"],
                wallet_id=wallet_id,
                tool_name="session-verification-tool",
                key_id=provisioned["key_id"],
            )
        ).allowed
        async with factory() as session:
            stored = await session.get(PermitModel, permit["permit_id"])
            assert stored is not None and stored.spent_credits == Decimal("1")
            reservations = (
                (
                    await session.execute(
                        select(PermitCallReservationModel).where(
                            PermitCallReservationModel.idempotency_record_id
                            == record_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(reservations) == 1
            assert reservations[0].state == "reserved"

    await asyncio.wait_for(validate_reserve_and_replay(), timeout=5)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "case", ["valid", "invalid_permit", "invalid_receipt", "non_refund"]
)
async def test_refund_completion_and_denials_use_one_postgres_connection(
    seeded_refund_reconciliation: SeededRefundReconciliation,
    case,
):
    seed = seeded_refund_reconciliation
    factory = _require_application_pool_one()
    if case != "valid":
        async with get_session_factory()() as session:
            if case == "invalid_permit":
                permit = await session.get(PermitModel, seed.permit.permit_id)
                assert permit is not None
                permit.signature = "invalid-permit-signature!"
            else:
                receipt = await session.get(ReceiptModel, seed.receipt_id)
                assert receipt is not None
                if case == "invalid_receipt":
                    # Exercise the historical-link lookup after the current
                    # signature fails, under the same one-connection bound.
                    receipt.idempotency_record_id = seed.record_id
                    receipt.signature = "invalid-receipt-signature!"
                else:
                    receipt.outcome = "success"
                    payload = receipts.get_receipt_service()._verification_payload(
                        receipt, include_linkage=True
                    )
                    receipt.signature = (
                        signing_keys.get_signing_key_service().sign_payload_with_key_id(
                            payload, receipt.signature_key_id
                        )[0]
                    )
            await session.commit()

    service = RefundReconciliationService()

    async def snapshot():
        async with factory() as session:
            wallet = await session.get(WalletModel, seed.permit.wallet_id)
            permit = await session.get(PermitModel, seed.permit.permit_id)
            receipt = await session.get(ReceiptModel, seed.receipt_id)
            record = await session.get(IdempotencyRecordModel, seed.record_id)
            assert wallet is not None and permit is not None
            assert receipt is not None and record is not None
            ledger = (
                (
                    await session.execute(
                        select(LedgerEntryModel)
                        .where(LedgerEntryModel.wallet_id == seed.permit.wallet_id)
                        .order_by(LedgerEntryModel.entry_id)
                    )
                )
                .scalars()
                .all()
            )
            return {
                "balance": wallet.balance,
                "lifetime_debits": wallet.lifetime_debits,
                "hourly_spent": wallet.hourly_spent,
                "daily_spent": wallet.daily_spent,
                "permit_spent": permit.spent_credits,
                "response": record.response_json,
                "receipt": (
                    receipt.signature,
                    receipt.outcome,
                    receipt.credits_charged,
                    receipt.idempotency_record_id,
                ),
                "ledger": [
                    (entry.entry_id, entry.action, entry.amount, entry.correlation_id)
                    for entry in ledger
                ],
            }

    async def exercise():
        before = await snapshot()
        signing_input = await receipts.get_receipt_service().signing_input(
            seed.receipt_id
        )
        if case == "invalid_receipt":
            assert signing_input is None
        else:
            assert signing_input is not None
            assert signing_input == canonical_json(json.loads(signing_input))
            public_key = await signing_keys.get_signing_key_service().get_public_key(
                seed.receipt_signing_key_id
            )
            assert public_key is not None
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(public_key.public_key_b64, validate=True)
            ).verify(
                base64.b64decode(before["receipt"][0], validate=True),
                signing_input.encode(),
            )
        if case != "valid":
            expected = {
                "invalid_permit": "refund_reconciliation_permit_invalid",
                "invalid_receipt": "refund_reconciliation_receipt_invalid",
                "non_refund": "refund_reconciliation_linkage_invalid",
            }[case]
            with pytest.raises(RefundReconciliationError, match=expected):
                await service.retry(seed.receipt_id)
            assert await snapshot() == before
            assert (
                json.loads(before["response"])["refund_reconciliation"]["status"]
                == "pending"
            )
            return

        resolved, replayed = await service.retry(seed.receipt_id)
        assert resolved.status == "resolved" and replayed is False
        after = await snapshot()
        assert after["balance"] == before["balance"] + seed.permit.amount
        for field in ("lifetime_debits", "hourly_spent", "daily_spent", "permit_spent"):
            assert after[field] == Decimal("0")
        assert after["receipt"] == before["receipt"]
        assert [entry for entry in after["ledger"] if entry[1] == "refund"] == [
            (seed.refund_entry_id, "refund", seed.permit.amount, seed.charge_entry_id)
        ]
        assert len(after["ledger"]) == len(before["ledger"]) + 1
        assert (
            json.loads(after["response"])["refund_reconciliation"]["status"]
            == "resolved"
        )
        repeated, replayed = await service.retry(seed.receipt_id)
        assert repeated.status == "resolved" and replayed is True
        assert (await service.get_item(seed.receipt_id)).status == "resolved"
        assert await snapshot() == after

    try:
        await asyncio.wait_for(exercise(), timeout=5)
    finally:
        if case == "invalid_receipt":
            # The reused fixture removes its identity before its legacy receipt.
            async with get_session_factory()() as session:
                receipt = await session.get(ReceiptModel, seed.receipt_id)
                assert receipt is not None
                receipt.idempotency_record_id = None
                await session.commit()


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("key_state", "checkpoint_state"),
    [
        ("cold", "valid"),
        ("warm", "valid"),
        ("disabled", "valid"),
        ("mismatched", "valid"),
        ("disabled", "terminal"),
        ("disabled", "mismatch"),
        ("retired", "terminal"),
        ("retired", "mismatch"),
        ("disabled", "missing_permit"),
        ("retired", "missing_permit"),
        ("disabled", "approval_mismatch"),
        ("retired", "approval_mismatch"),
        ("cold", "terminal_race"),
    ],
)
async def test_pending_refund_creation_uses_one_postgres_connection(
    seeded_permit: SeededPermit,
    key_state,
    checkpoint_state,
    monkeypatch,
):
    seed = seeded_permit
    factory = _require_application_pool_one()
    signer = signing_keys.get_signing_key_service()
    public_key_b64 = signer._public_key_b64()
    signing_key_id = signer._key_id
    assert await signer.get_public_key(signing_key_id) is None
    if key_state == "warm":
        await signer.ensure_active_key()

    record_id = f"idm-pending-{seed.permit_id}"
    charge_id = f"charge-pending-{seed.permit_id}"
    approval_id = f"approval-pending-{seed.permit_id}"
    request_payload = {"tool": seed.tool_name, "action": "pending-refund"}
    kwargs = {
        "wallet_id": seed.wallet_id,
        "endpoint": "/mcp/messages",
        "idempotency_key": record_id,
        "permit_id": seed.permit_id,
        "key_id": None,
        "tool_name": seed.tool_name,
        "request_payload": request_payload,
        "ledger_entry_id": charge_id,
        "credits_authorized": seed.amount,
        "credits_charged": seed.amount,
        "audit_event_id": None,
        "reason": "refund_failed",
    }
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, seed.wallet_id)
        permit = await session.get(PermitModel, seed.permit_id)
        assert wallet is not None and permit is not None
        wallet.balance -= seed.amount
        wallet.lifetime_debits = seed.amount
        wallet.hourly_spent = seed.amount
        wallet.daily_spent = seed.amount
        charged_balance = wallet.balance
        permit.spent_credits = seed.amount
        if checkpoint_state == "approval_mismatch":
            permit.requires_human_approval = True
            session.add(
                HumanApprovalModel(
                    approval_id=approval_id,
                    wallet_id=seed.wallet_id,
                    permit_id=seed.permit_id,
                    tool=seed.tool_name,
                    idempotency_key="different-approved-logical-action",
                    status="consumed",
                    expires_at=permit.expires_at,
                )
            )
            kwargs["approval_id"] = approval_id
        if key_state in {"disabled", "mismatched", "retired"}:
            session.add(
                SigningKeyModel(
                    key_id=signing_key_id,
                    public_key_b64=(
                        public_key_b64
                        if key_state in {"disabled", "retired"}
                        else "mismatched-public-key"
                    ),
                    status=key_state if key_state != "mismatched" else "active",
                    activated_at=utc_now(),
                    retired_at=utc_now() if key_state == "retired" else None,
                )
            )
        session.add(
            LedgerEntryModel(
                entry_id=charge_id,
                wallet_id=seed.wallet_id,
                action="debit",
                amount=-seed.amount,
                balance_after=wallet.balance,
                service_category="agent_comms",
                request_path="/mcp/messages",
                timestamp=utc_now(),
            )
        )
        await session.flush()
        session.add(
            IdempotencyRecordModel(
                record_id=record_id,
                wallet_id=seed.wallet_id,
                endpoint=kwargs["endpoint"],
                idempotency_key=record_id,
                request_hash=sha256_hex(request_payload),
                ledger_entry_id=charge_id,
                operation_kind="local",
                response_json="{}" if checkpoint_state == "terminal" else None,
            )
        )
        await session.commit()

    if checkpoint_state == "mismatch":
        kwargs["ledger_entry_id"] = "different-debit-checkpoint"
    elif checkpoint_state == "missing_permit":
        kwargs["permit_id"] = "missing-pending-refund-permit"
    async with factory() as session:
        key = await session.get(SigningKeyModel, signing_key_id)
        key_before = (
            (key.status, key.public_key_b64, key.activated_at, key.retired_at)
            if key is not None
            else None
        )
    service = RefundReconciliationService()
    terminal_response = '{"completed_elsewhere":true}'
    preparations = 0
    real_prepare = signer.ensure_active_key

    async def terminalize_at_key_preparation():
        # The preflight has released its sole connection. Persist a competing
        # terminal result before invoking the real key lifecycle and locked
        # recheck; neither the factory nor cryptographic operation is replaced.
        nonlocal preparations
        preparations += 1
        assert preparations == 1
        async with factory() as session:
            record = await session.get(IdempotencyRecordModel, record_id)
            assert record is not None
            assert record.response_json is None and record.response_reference is None
            record.response_json = terminal_response
            await session.commit()
        return await real_prepare()

    if checkpoint_state == "terminal_race":
        monkeypatch.setattr(signer, "ensure_active_key", terminalize_at_key_preparation)

    async def exercise():
        created = None
        if checkpoint_state != "valid":
            with pytest.raises(
                RefundReconciliationError,
                match=(
                    "refund_reconciliation_approval_linkage_invalid"
                    if checkpoint_state == "approval_mismatch"
                    else "refund_reconciliation_checkpoint_invalid"
                ),
            ):
                await service.create_pending(**kwargs)
        elif key_state in {"disabled", "mismatched"}:
            reason = (
                "signing_key_disabled"
                if key_state == "disabled"
                else "signing_key_id_public_key_mismatch"
            )
            with pytest.raises(SigningKeyError, match=reason):
                await service.create_pending(**kwargs)
        else:
            created, pending = await service.create_pending(**kwargs)
            assert created.outcome == "failed_unrefunded"
            assert created.signature_key_id == signing_key_id
            assert created.idempotency_record_id == record_id
            assert created.ledger_entry_id == charge_id
            assert created.credits_charged == seed.amount
            assert pending["status"] == "pending"
            valid, reason, _ = await receipts.get_receipt_service().verify_receipt(
                created.receipt_id
            )
            assert (valid, reason) == (True, None)

        async with factory() as session:
            wallet = await session.get(WalletModel, seed.wallet_id)
            permit = await session.get(PermitModel, seed.permit_id)
            record = await session.get(IdempotencyRecordModel, record_id)
            key = await session.get(SigningKeyModel, signing_key_id)
            assert wallet is not None and permit is not None and record is not None
            assert key is not None
            assert wallet.balance == charged_balance
            assert wallet.lifetime_debits == seed.amount
            assert wallet.hourly_spent == seed.amount
            assert wallet.daily_spent == seed.amount
            assert permit.spent_credits == seed.amount
            stored_receipts = (
                (
                    await session.execute(
                        select(ReceiptModel).where(
                            ReceiptModel.idempotency_record_id == record_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            ledger = (
                (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            LedgerEntryModel.wallet_id == seed.wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [(entry.entry_id, entry.amount) for entry in ledger] == [
                (charge_id, -seed.amount)
            ]
            if created is None:
                assert stored_receipts == []
                assert record.response_reference is None
                expected_response = {
                    "terminal": "{}",
                    "terminal_race": terminal_response,
                }.get(checkpoint_state)
                assert record.response_json == expected_response
                if checkpoint_state == "terminal_race":
                    assert preparations == 1
                    assert key_before is None
                    assert key.status == "active"
                    assert key.public_key_b64 == public_key_b64
                else:
                    assert (
                        key.status,
                        key.public_key_b64,
                        key.activated_at,
                        key.retired_at,
                    ) == key_before
                if key_state in {"disabled", "retired"}:
                    assert key.status == key_state
                    assert key.public_key_b64 == public_key_b64
                    if key_state == "retired":
                        assert key.retired_at is not None
                elif key_state == "mismatched":
                    assert key.public_key_b64 == "mismatched-public-key"
                if checkpoint_state == "approval_mismatch":
                    approval = await session.get(HumanApprovalModel, approval_id)
                    assert approval is not None and approval.status == "consumed"
                    assert (
                        approval.idempotency_key == "different-approved-logical-action"
                    )
            else:
                assert len(stored_receipts) == 1
                assert record.response_reference == created.receipt_id
                state = json.loads(record.response_json)
                assert state["receipt"]["receipt_id"] == created.receipt_id
                assert state["refund_reconciliation"]["status"] == "pending"
                assert key.status == "active" and key.public_key_b64 == public_key_b64

    try:
        await asyncio.wait_for(exercise(), timeout=5)
    finally:
        async with get_session_factory()() as session:
            await session.execute(
                delete(ReceiptModel).where(
                    ReceiptModel.idempotency_record_id == record_id
                )
            )
            await session.execute(
                delete(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.record_id == record_id
                )
            )
            await session.execute(
                delete(LedgerEntryModel).where(LedgerEntryModel.entry_id == charge_id)
            )
            await session.execute(
                delete(HumanApprovalModel).where(
                    HumanApprovalModel.approval_id == approval_id
                )
            )
            await session.execute(
                delete(SigningKeyModel).where(SigningKeyModel.key_id == signing_key_id)
            )
            await session.commit()


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("signature_style", ["current", "legacy"])
@pytest.mark.parametrize(
    "case", ["valid", "malformed", "tampered", "missing_receipt", "disabled", "retired"]
)
async def test_public_receipt_export_uses_application_pool_and_authentic_signatures(
    seeded_refund_reconciliation: SeededRefundReconciliation,
    signature_style,
    case,
):
    seed = seeded_refund_reconciliation
    factory = _require_application_pool_one()
    service = receipts.get_receipt_service()
    signer = signing_keys.get_signing_key_service()
    async with factory() as session:
        receipt = await session.get(ReceiptModel, seed.receipt_id)
        record = await session.get(IdempotencyRecordModel, seed.record_id)
        key = await session.get(SigningKeyModel, seed.receipt_signing_key_id)
        assert receipt is not None and record is not None and key is not None
        public_key_bytes = base64.b64decode(key.public_key_b64, validate=True)
        # The fixture signs this receipt before any linkage is backfilled.
        # Verify those authentic historical bytes independently before changing it.
        legacy_payload = service._verification_payload(receipt, include_linkage=False)
        legacy_input = canonical_json(legacy_payload)
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            base64.b64decode(receipt.signature, validate=True), legacy_input.encode()
        )
        assert receipt.idempotency_record_id is None
        assert record.response_reference == receipt.receipt_id
        assert record.wallet_id == receipt.wallet_id
        assert record.request_hash == receipt.request_hash
        receipt.idempotency_record_id = record.record_id
        if signature_style == "current":
            payload = service._verification_payload(receipt, include_linkage=True)
            receipt.signature = signer.sign_payload_with_key_id(
                payload, receipt.signature_key_id
            )[0]
            expected_input = canonical_json(payload)
        else:
            # Migration-compatible case: the new unambiguous identity link was
            # never signed. The original signature and its exact bytes survive.
            expected_input = legacy_input
            assert "idempotency_record_id" not in json.loads(expected_input)
        signature = receipt.signature
        if case == "malformed":
            receipt.signature = "invalid-base64-signature!"
        elif case == "tampered":
            receipt.tool = "tampered-after-signing"
        elif case in {"disabled", "retired"}:
            key.status = case
            key.retired_at = utc_now()
        await session.commit()

    async def verify_public_export():
        # A missing signing-key row is prevented by the receipt's database FK;
        # missing receipt lookup is the public API's reachable absence case.
        lookup_id = (
            f"missing-{seed.receipt_id}"
            if case == "missing_receipt"
            else seed.receipt_id
        )
        exported = await service.signing_input(lookup_id)
        valid, reason, _ = await service.verify_receipt(lookup_id)
        if case in {"valid", "retired"}:
            assert exported == expected_input
            assert (valid, reason) == (True, None)
            assert canonical_json(json.loads(exported)) == exported
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                base64.b64decode(signature, validate=True), exported.encode()
            )
        else:
            assert exported is None
            assert valid is False
            assert reason == (
                "receipt_not_found"
                if case == "missing_receipt"
                else "receipt_signature_invalid"
            )

    try:
        await asyncio.wait_for(verify_public_export(), timeout=5)
    finally:
        # Restore the fixture's original legacy linkage for its FK-safe teardown.
        async with factory() as session:
            receipt = await session.get(ReceiptModel, seed.receipt_id)
            assert receipt is not None
            receipt.idempotency_record_id = None
            await session.commit()
