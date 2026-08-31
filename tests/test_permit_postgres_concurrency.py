"""PostgreSQL row-lock proofs for permit authorization and revocation.

SQLite does not implement ``SELECT ... FOR UPDATE`` semantics, so these tests
only run when explicitly pointed at an isolated PostgreSQL database. The CI
job in ``.github/workflows/ci.yml`` supplies that database and opt-in flag.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.jwt import get_jwt_service
from app.core.time import utc_now
from app.db.database import get_engine, get_session_factory
from app.db.models import (
    BillingAlertModel,
    ControlPlaneAuditEventModel,
    HumanApprovalModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitCallReservationModel,
    PermitModel,
    ReceiptModel,
    RefreshTokenModel,
    SigningKeyModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    get_idempotency_service,
)
from app.services.human_approval import HumanApprovalService, invoke_request_hash
from app.services.mcp_dispatch_attempts import (
    DispatchClaimUnavailableError,
    McpDispatchAttemptService,
    get_mcp_dispatch_attempt_service,
)
from app.services.mcp_dispatch_reconciliation import (
    McpDispatchReconciliationService,
)
from app.services.permits import PermitService, PermitValidation
from app.services.receipts import ReceiptError, get_receipt_service
from app.services.refund_reconciliation import (
    RefundReconciliationService,
    build_pending_refund_reconciliation,
)
from app.services.service_registry import get_service_registry
from app.services.signing_keys import canonical_json, sha256_hex
from app.services.upstream_mcp import UpstreamMcpResult
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


TEST_JWT_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="


@dataclass(frozen=True)
class SeededPermit:
    permit_id: str
    wallet_id: str
    signing_key_id: str
    tool_name: str
    amount: Decimal


@dataclass(frozen=True)
class SeededRefundReconciliation:
    permit: SeededPermit
    receipt_id: str
    charge_entry_id: str
    refund_entry_id: str
    record_id: str
    receipt_signing_key_id: str


class PausedUpstreamExecutor:
    """Fake partner executor that holds one dispatched request in flight."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.dispatch_count = 0
        self.dispatched = asyncio.Event()
        self.release = asyncio.Event()

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Callable[[], Awaitable[None]],
    ) -> UpstreamMcpResult:
        self.calls.append(
            {
                "arguments": arguments,
                "invocation_id": invocation_id,
                "idempotency_key": idempotency_key,
            }
        )
        await before_dispatch()
        self.dispatch_count += 1
        self.dispatched.set()
        await self.release.wait()
        payload = {
            "content": [{"type": "text", "text": "partner response"}],
            "structuredContent": {"echo": arguments},
            "isError": False,
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return UpstreamMcpResult(
            payload=payload,
            canonical_json=canonical,
            response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            size_bytes=len(canonical.encode()),
            is_error=False,
        )


def _require_opted_in_postgres() -> None:
    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        pytest.skip("requires a PostgreSQL DATABASE_URL for real row-lock semantics")
    if os.environ.get("RUN_POSTGRES_CONCURRENCY_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_CONCURRENCY_TESTS=1 only with an isolated "
            "PostgreSQL test database"
        )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded_permit() -> SeededPermit:
    _require_opted_in_postgres()

    suffix = uuid.uuid4().hex[:16]
    wallet_id = f"wallet-pg-{suffix}"
    permit_id = f"permit-pg-{suffix}"
    signing_key_id = f"key-pg-{suffix}"
    tool_name = f"tool-pg-{suffix}"
    amount = Decimal("7")
    now = utc_now()
    expires_at = now + timedelta(minutes=5)
    nonce = uuid.uuid4().hex
    scopes = [f"tool:{tool_name}:invoke", "billing:charge"]
    allowed_tools = [tool_name]

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    signing_payload = {
        "permit_id": permit_id,
        "issuer_wallet_id": wallet_id,
        "subject_wallet_id": wallet_id,
        "subject_key_id": None,
        "scopes": scopes,
        "allowed_tools": allowed_tools,
        "max_credits": amount,
        "expires_at": expires_at,
        "nonce": nonce,
        "status": "active",
        "issued_at": now,
        "alg": "Ed25519",
        "kid": signing_key_id,
    }
    signing_payload["payload_hash"] = sha256_hex(signing_payload)
    signature = base64.b64encode(
        private_key.sign(canonical_json(signing_payload).encode())
    ).decode()

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(
                WalletModel(
                    wallet_id=wallet_id,
                    wallet_type="agent",
                    balance=Decimal("100"),
                )
            )
            session.add(
                SigningKeyModel(
                    key_id=signing_key_id,
                    public_key_b64=base64.b64encode(public_key).decode(),
                    status="active",
                    activated_at=now,
                )
            )
            await session.flush()
            session.add(
                PermitModel(
                    permit_id=permit_id,
                    issuer_wallet_id=wallet_id,
                    subject_wallet_id=wallet_id,
                    subject_key_id=None,
                    scopes_json=json.dumps(scopes),
                    allowed_tools_json=json.dumps(allowed_tools),
                    max_credits=amount,
                    spent_credits=Decimal("0"),
                    expires_at=expires_at,
                    nonce=nonce,
                    status="active",
                    signature=signature,
                    key_id=signing_key_id,
                    issued_at=now,
                )
            )

    seed = SeededPermit(
        permit_id=permit_id,
        wallet_id=wallet_id,
        signing_key_id=signing_key_id,
        tool_name=tool_name,
        amount=amount,
    )
    try:
        yield seed
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(PermitModel).where(PermitModel.permit_id == permit_id)
                )
                await session.execute(
                    delete(BillingAlertModel).where(
                        BillingAlertModel.wallet_id == wallet_id
                    )
                )
                await session.execute(
                    delete(WalletModel).where(WalletModel.wallet_id == wallet_id)
                )
                await session.execute(
                    delete(SigningKeyModel).where(
                        SigningKeyModel.key_id == signing_key_id
                    )
                )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded_refund_reconciliation(
    seeded_permit: SeededPermit,
) -> SeededRefundReconciliation:
    """Persist one fully linked failed-refund work item and its signed proof."""

    suffix = uuid.uuid4().hex[:16]
    charge_entry_id = f"charge-pg-{suffix}"
    record_id = f"idem-pg-{suffix}"
    factory = get_session_factory()
    now = utc_now()

    async with factory() as session:
        async with session.begin():
            wallet = await session.get(WalletModel, seeded_permit.wallet_id)
            permit = await session.get(PermitModel, seeded_permit.permit_id)
            assert wallet is not None
            assert permit is not None
            wallet.balance -= seeded_permit.amount
            wallet.lifetime_debits = seeded_permit.amount
            wallet.hourly_spent = seeded_permit.amount
            wallet.daily_spent = seeded_permit.amount
            wallet.updated_at = now
            permit.spent_credits = seeded_permit.amount
            permit.updated_at = now
            session.add(wallet)
            session.add(permit)
            session.add(
                LedgerEntryModel(
                    entry_id=charge_entry_id,
                    wallet_id=seeded_permit.wallet_id,
                    action="debit",
                    amount=-seeded_permit.amount,
                    balance_after=wallet.balance,
                    service_category="agent_comms",
                    description="PostgreSQL reconciliation concurrency charge",
                    request_path="/mcp/messages",
                    correlation_id=f"request-pg-{suffix}",
                    timestamp=now,
                )
            )

    request_payload = {"id": f"request-pg-{suffix}"}
    receipt = await get_receipt_service().create_receipt(
        permit_id=seeded_permit.permit_id,
        wallet_id=seeded_permit.wallet_id,
        key_id=None,
        tool=seeded_permit.tool_name,
        request_payload=request_payload,
        response_payload={"error": "refund_failed"},
        ledger_entry_id=charge_entry_id,
        credits_authorized=seeded_permit.amount,
        credits_charged=seeded_permit.amount,
        outcome="failed_unrefunded",
        audit_event_id=None,
    )
    reconciliation = build_pending_refund_reconciliation(
        receipt_id=receipt.receipt_id,
        wallet_id=seeded_permit.wallet_id,
        permit_id=seeded_permit.permit_id,
        ledger_entry_id=charge_entry_id,
        credits=seeded_permit.amount,
    )
    async with factory() as session:
        async with session.begin():
            session.add(
                IdempotencyRecordModel(
                    record_id=record_id,
                    wallet_id=seeded_permit.wallet_id,
                    endpoint="/mcp/messages",
                    idempotency_key=f"refund-pg-{suffix}",
                    request_hash=sha256_hex(request_payload),
                    response_reference=receipt.receipt_id,
                    response_json=json.dumps(
                        {
                            "content": [],
                            "isError": True,
                            "receipt": receipt.model_dump(mode="json"),
                            "refund_reconciliation": reconciliation,
                        },
                        default=str,
                    ),
                    status_code=500,
                    ledger_entry_id=charge_entry_id,
                )
            )

    seed = SeededRefundReconciliation(
        permit=seeded_permit,
        receipt_id=receipt.receipt_id,
        charge_entry_id=charge_entry_id,
        refund_entry_id=reconciliation["refund_entry_id"],
        record_id=record_id,
        receipt_signing_key_id=receipt.signature_key_id,
    )
    try:
        yield seed
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.record_id == record_id
                    )
                )
                await session.execute(
                    delete(ReceiptModel).where(
                        ReceiptModel.receipt_id == receipt.receipt_id
                    )
                )
                await session.execute(
                    delete(LedgerEntryModel).where(
                        LedgerEntryModel.entry_id.in_(
                            [charge_entry_id, reconciliation["refund_entry_id"]]
                        )
                    )
                )
                if receipt.signature_key_id != seeded_permit.signing_key_id:
                    await session.execute(
                        delete(SigningKeyModel).where(
                            SigningKeyModel.key_id == receipt.signature_key_id
                        )
                    )


def _authorization_kwargs(seed: SeededPermit) -> dict[str, object]:
    return {
        "permit_id": seed.permit_id,
        "wallet_id": seed.wallet_id,
        "tool_name": seed.tool_name,
        "estimated_credits": seed.amount,
        "key_id": None,
    }


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_operation_key_charge_is_one_debit_in_postgres(
    seeded_permit: SeededPermit,
) -> None:
    """The idempotency row lock serializes velocity accounting and debit."""
    suffix = uuid.uuid4().hex[:16]
    record_id = f"idem-charge-pg-{suffix}"
    request_hash = sha256_hex({"tool": seeded_permit.tool_name, "value": suffix})
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(
                IdempotencyRecordModel(
                    record_id=record_id,
                    wallet_id=seeded_permit.wallet_id,
                    endpoint="/mcp/messages",
                    idempotency_key=f"charge-pg-{suffix}",
                    request_hash=request_hash,
                )
            )

    money = get_agent_money()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                money.charge(
                    wallet_id=seeded_permit.wallet_id,
                    service_category=ServiceCategory.AGENT_COMMS,
                    units=Decimal("1"),
                    request_path="/mcp/messages",
                    operation_key=record_id,
                ),
                money.charge(
                    wallet_id=seeded_permit.wallet_id,
                    service_category=ServiceCategory.AGENT_COMMS,
                    units=Decimal("1"),
                    request_path="/mcp/messages",
                    operation_key=record_id,
                ),
            ),
            timeout=10,
        )
        assert results[0].entry_id == results[1].entry_id  # type: ignore[union-attr]

        async with factory() as session:
            wallet = await session.get(WalletModel, seeded_permit.wallet_id)
            debits = (
                (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            LedgerEntryModel.wallet_id == seeded_permit.wallet_id,
                            LedgerEntryModel.operation_key == record_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert wallet is not None
        assert wallet.balance == Decimal("98.5")
        assert wallet.hourly_spent == Decimal("1.5")
        assert wallet.daily_spent == Decimal("1.5")
        assert len(debits) == 1
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(LedgerEntryModel).where(
                        LedgerEntryModel.operation_key == record_id
                    )
                )
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.record_id == record_id
                    )
                )


@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_and_canonical_mcp_identities_serialize_in_postgres(
    seeded_permit: SeededPermit,
) -> None:
    """A rolling old/new worker race can establish only one operation row."""
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:16]
    idempotency_key = f"mcp-identity-pg-{suffix}"
    factory = get_session_factory()
    start = asyncio.Event()
    legacy_ready = asyncio.Event()
    canonical_ready = asyncio.Event()

    async def insert_identity(
        *,
        record_id: str,
        endpoint: str,
        ready: asyncio.Event,
    ) -> str:
        async with factory() as session:
            session.add(
                IdempotencyRecordModel(
                    record_id=record_id,
                    wallet_id=seeded_permit.wallet_id,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    request_hash=sha256_hex(
                        {"record_id": record_id, "endpoint": endpoint}
                    ),
                )
            )
            ready.set()
            await start.wait()
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return record_id

    legacy_task = asyncio.create_task(
        insert_identity(
            record_id=f"idem-legacy-pg-{suffix}",
            endpoint="/mcp/messages",
            ready=legacy_ready,
        )
    )
    canonical_task = asyncio.create_task(
        insert_identity(
            record_id=f"idem-current-pg-{suffix}",
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            ready=canonical_ready,
        )
    )
    try:
        await asyncio.wait_for(
            asyncio.gather(legacy_ready.wait(), canonical_ready.wait()),
            timeout=5,
        )
        start.set()
        results = await asyncio.wait_for(
            asyncio.gather(
                legacy_task,
                canonical_task,
                return_exceptions=True,
            ),
            timeout=10,
        )
        assert sum(isinstance(result, str) for result in results) == 1
        assert sum(isinstance(result, IntegrityError) for result in results) == 1

        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.wallet_id == seeded_permit.wallet_id,
                            IdempotencyRecordModel.idempotency_key == idempotency_key,
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].endpoint in {
            "/mcp/messages",
            GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        }
    finally:
        start.set()
        pending = [task for task in (legacy_task, canonical_task) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.wallet_id == seeded_permit.wallet_id,
                        IdempotencyRecordModel.idempotency_key == idempotency_key,
                    )
                )


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_authorizations_admit_exactly_one_budget_reservation(
    seeded_permit: SeededPermit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second full-budget authorization waits and observes the first write."""

    service = PermitService()
    original_validate = service._validate_model_for_action
    first_validation_entered = asyncio.Event()
    second_validation_entered = asyncio.Event()
    release_first_validation = asyncio.Event()
    validation_calls = 0

    async def delayed_first_validation(**kwargs: object) -> PermitValidation:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            first_validation_entered.set()
            await release_first_validation.wait()
        else:
            second_validation_entered.set()
        return await original_validate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_validate_model_for_action", delayed_first_validation)

    first = asyncio.create_task(
        service.authorize_and_reserve(**_authorization_kwargs(seeded_permit))  # type: ignore[arg-type]
    )
    await asyncio.wait_for(first_validation_entered.wait(), timeout=5)

    second_started = asyncio.Event()

    async def run_second() -> PermitValidation:
        second_started.set()
        return await service.authorize_and_reserve(
            **_authorization_kwargs(seeded_permit)  # type: ignore[arg-type]
        )

    second = asyncio.create_task(run_second())
    await asyncio.wait_for(second_started.wait(), timeout=5)
    await asyncio.sleep(0.1)
    second_reached_validation_while_locked = second_validation_entered.is_set()

    release_first_validation.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)

    assert second_reached_validation_while_locked is False
    assert sum(result.allowed for result in results) == 1
    denied = next(result for result in results if not result.allowed)
    assert denied.reason == "permit_budget_exceeded"

    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, seeded_permit.permit_id)
        assert model is not None
        assert model.spent_credits == seeded_permit.amount


@pytest.mark.asyncio(loop_scope="session")
async def test_authorization_then_revocation_is_one_valid_serial_order(
    seeded_permit: SeededPermit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revocation waits when authorization already owns the permit row lock."""

    service = PermitService()
    original_validate = service._validate_model_for_action
    authorization_has_lock = asyncio.Event()
    release_authorization = asyncio.Event()

    async def paused_validation(**kwargs: object) -> PermitValidation:
        authorization_has_lock.set()
        await release_authorization.wait()
        return await original_validate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_validate_model_for_action", paused_validation)

    authorization = asyncio.create_task(
        service.authorize_and_reserve(**_authorization_kwargs(seeded_permit))  # type: ignore[arg-type]
    )
    await asyncio.wait_for(authorization_has_lock.wait(), timeout=5)

    revocation_started = asyncio.Event()

    async def revoke() -> object:
        revocation_started.set()
        return await service.revoke_permit(seeded_permit.permit_id)

    revocation = asyncio.create_task(revoke())
    await asyncio.wait_for(revocation_started.wait(), timeout=5)
    await asyncio.sleep(0.1)
    revocation_completed_while_locked = revocation.done()

    release_authorization.set()
    authorization_result, revoked = await asyncio.wait_for(
        asyncio.gather(authorization, revocation), timeout=10
    )

    assert revocation_completed_while_locked is False
    assert authorization_result.allowed is True
    assert revoked.status == "revoked"

    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, seeded_permit.permit_id)
        assert model is not None
        assert model.status == "revoked"
        assert model.spent_credits == seeded_permit.amount


@pytest.mark.asyncio(loop_scope="session")
async def test_revocation_then_authorization_is_other_valid_serial_order(
    seeded_permit: SeededPermit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authorization waits for an in-flight revocation and then denies."""

    service = PermitService()
    original_validate = service._validate_model_for_action
    authorization_started = asyncio.Event()
    authorization_reached_validation = asyncio.Event()

    async def observed_validation(**kwargs: object) -> PermitValidation:
        authorization_reached_validation.set()
        return await original_validate(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_validate_model_for_action", observed_validation)

    factory = get_session_factory()
    async with factory() as revocation_session:
        async with revocation_session.begin():
            model = await revocation_session.get(
                PermitModel,
                seeded_permit.permit_id,
                with_for_update=True,
            )
            assert model is not None
            model.status = "revoked"
            model.revoked_at = utc_now()
            revocation_session.add(model)

            async def authorize() -> PermitValidation:
                authorization_started.set()
                return await service.authorize_and_reserve(
                    **_authorization_kwargs(seeded_permit)  # type: ignore[arg-type]
                )

            authorization = asyncio.create_task(authorize())
            await asyncio.wait_for(authorization_started.wait(), timeout=5)
            await asyncio.sleep(0.1)
            authorization_validated_while_locked = (
                authorization_reached_validation.is_set()
            )

    authorization_result = await asyncio.wait_for(authorization, timeout=10)

    assert authorization_validated_while_locked is False
    assert authorization_result.allowed is False
    assert authorization_result.reason == "permit_revoked"

    async with factory() as session:
        model = await session.get(PermitModel, seeded_permit.permit_id)
        assert model is not None
        assert model.status == "revoked"
        assert model.spent_credits == Decimal("0")


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_refund_reconciliation_is_exactly_once_in_postgres(
    seeded_refund_reconciliation: SeededRefundReconciliation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent workers serialize on the durable work-item row lock."""

    receipt_service = get_receipt_service()
    original_verify = receipt_service.verify_model
    first_worker_has_lock = asyncio.Event()
    second_worker_reached_verification = asyncio.Event()
    release_first_worker = asyncio.Event()
    verification_calls = 0

    async def pause_first_worker(receipt: ReceiptModel, **kwargs: Any) -> bool:
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls == 1:
            first_worker_has_lock.set()
            await release_first_worker.wait()
        else:
            second_worker_reached_verification.set()
        return await original_verify(receipt, **kwargs)

    monkeypatch.setattr(receipt_service, "verify_model", pause_first_worker)
    first_service = RefundReconciliationService()
    second_service = RefundReconciliationService()

    # Bypass the shared asyncio lock to model workers in separate processes.
    first = asyncio.create_task(
        first_service._retry_locked(seeded_refund_reconciliation.receipt_id)
    )
    await asyncio.wait_for(first_worker_has_lock.wait(), timeout=5)

    second_started = asyncio.Event()

    async def run_second_worker():  # noqa: ANN202
        second_started.set()
        return await second_service._retry_locked(
            seeded_refund_reconciliation.receipt_id
        )

    second = asyncio.create_task(run_second_worker())
    await asyncio.wait_for(second_started.wait(), timeout=5)
    await asyncio.sleep(0.1)
    second_verified_while_first_held_lock = second_worker_reached_verification.is_set()

    release_first_worker.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)

    assert second_verified_while_first_held_lock is False
    assert [replayed for _item, replayed in results] == [False, True]
    assert all(item.status == "resolved" for item, _replayed in results)

    seed = seeded_refund_reconciliation
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, seed.permit.wallet_id)
        permit = await session.get(PermitModel, seed.permit.permit_id)
        receipt = await session.get(ReceiptModel, seed.receipt_id)
        record = await session.get(IdempotencyRecordModel, seed.record_id)
        refunds = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.correlation_id == seed.charge_entry_id,
                        LedgerEntryModel.action == "refund",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert wallet is not None
    assert wallet.balance == Decimal("100")
    assert wallet.lifetime_debits == Decimal("0")
    assert wallet.hourly_spent == Decimal("0")
    assert wallet.daily_spent == Decimal("0")
    assert permit is not None
    assert permit.spent_credits == Decimal("0")
    assert receipt is not None
    assert receipt.outcome == "failed_unrefunded"
    assert record is not None
    resolved_payload = json.loads(record.response_json or "{}")
    assert resolved_payload["refund_reconciliation"]["status"] == "resolved"
    assert len(refunds) == 1
    assert refunds[0].entry_id == seed.refund_entry_id
    assert refunds[0].amount == seed.permit.amount


def _receipt_kwargs(
    seed: SeededPermit,
    *,
    record_id: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "permit_id": seed.permit_id,
        "wallet_id": seed.wallet_id,
        "key_id": None,
        "tool": seed.tool_name,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "ledger_entry_id": None,
        "credits_authorized": seed.amount,
        "credits_charged": Decimal("0"),
        "outcome": "denied",
        "audit_event_id": None,
        "idempotency_record_id": record_id,
    }


async def _create_receipt_idempotency_record(
    seed: SeededPermit,
    *,
    request_payload: dict[str, Any],
) -> str:
    suffix = uuid.uuid4().hex[:16]
    record_id = f"idem-receipt-pg-{suffix}"
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(
                IdempotencyRecordModel(
                    record_id=record_id,
                    wallet_id=seed.wallet_id,
                    endpoint="/mcp/messages",
                    idempotency_key=f"receipt-pg-{suffix}",
                    request_hash=sha256_hex(request_payload),
                )
            )
    return record_id


async def _delete_receipt_idempotency_record(record_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
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


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_receipt_get_or_create_returns_one_receipt_in_postgres(
    seeded_permit: SeededPermit,
) -> None:
    """A unique-key race recovers the committed receipt instead of duplicating it."""
    request_payload = {"message": uuid.uuid4().hex}
    response_payload = {"content": [{"type": "text", "text": "ok"}]}
    record_id = await _create_receipt_idempotency_record(
        seeded_permit,
        request_payload=request_payload,
    )
    receipt_service = get_receipt_service()
    kwargs = _receipt_kwargs(
        seeded_permit,
        record_id=record_id,
        request_payload=request_payload,
        response_payload=response_payload,
    )

    try:
        first, second = await asyncio.wait_for(
            asyncio.gather(
                receipt_service.create_receipt(**kwargs),
                receipt_service.create_receipt(**kwargs),
            ),
            timeout=10,
        )

        assert first.receipt_id == second.receipt_id
        factory = get_session_factory()
        async with factory() as session:
            persisted = (
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
        assert len(persisted) == 1
        assert persisted[0].receipt_id == first.receipt_id
        valid, reason, verified = await receipt_service.verify_receipt(first.receipt_id)
        assert valid is True
        assert reason is None
        assert verified is not None
        assert verified.receipt_id == first.receipt_id
    finally:
        await _delete_receipt_idempotency_record(record_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_conflicting_concurrent_receipt_reuse_rejects_in_postgres(
    seeded_permit: SeededPermit,
) -> None:
    """Only one evidence payload may bind to an idempotency record."""
    request_payload = {"message": uuid.uuid4().hex}
    first_response = {"content": [{"type": "text", "text": "first"}]}
    conflicting_response = {"content": [{"type": "text", "text": "changed"}]}
    record_id = await _create_receipt_idempotency_record(
        seeded_permit,
        request_payload=request_payload,
    )
    receipt_service = get_receipt_service()

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                receipt_service.create_receipt(
                    **_receipt_kwargs(
                        seeded_permit,
                        record_id=record_id,
                        request_payload=request_payload,
                        response_payload=first_response,
                    )
                ),
                receipt_service.create_receipt(
                    **_receipt_kwargs(
                        seeded_permit,
                        record_id=record_id,
                        request_payload=request_payload,
                        response_payload=conflicting_response,
                    )
                ),
                return_exceptions=True,
            ),
            timeout=10,
        )
        successes = [result for result in results if not isinstance(result, Exception)]
        conflicts = [result for result in results if isinstance(result, ReceiptError)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert conflicts[0].reason == "receipt_idempotency_conflict"

        factory = get_session_factory()
        async with factory() as session:
            persisted = (
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
        assert len(persisted) == 1
        assert persisted[0].receipt_id == successes[0].receipt_id
        assert persisted[0].response_hash in {
            sha256_hex(first_response),
            sha256_hex(conflicting_response),
        }
    finally:
        await _delete_receipt_idempotency_record(record_id)


def _register_paused_upstream(
    tool_name: str,
    executor: PausedUpstreamExecutor,
) -> None:
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="PostgreSQL Design Partner Tool",
        description="Controlled remote MCP concurrency test tool",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        credits_per_unit=2.0,
        upstream_tool_name="partner.echo",
        upstream_origin="https://partner.example",
    )


def _upstream_call_body(
    *,
    tool_name: str,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
    message: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idempotency_key}",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": message},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


async def _load_governed_operation_rows(
    *,
    wallet_id: str,
    idempotency_key: str,
) -> tuple[
    IdempotencyRecordModel,
    list[LedgerEntryModel],
    list[McpDispatchAttemptModel],
    list[ReceiptModel],
]:
    factory = get_session_factory()
    async with factory() as session:
        record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.wallet_id == wallet_id,
                    IdempotencyRecordModel.endpoint
                    == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()
        debits = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.wallet_id == wallet_id,
                        LedgerEntryModel.operation_key == record.record_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(McpDispatchAttemptModel).where(
                        McpDispatchAttemptModel.idempotency_record_id
                        == record.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
        receipts = (
            (
                await session.execute(
                    select(ReceiptModel).where(
                        ReceiptModel.idempotency_record_id == record.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
    return record, list(debits), list(attempts), list(receipts)


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_identical_upstream_requests_share_one_result_in_postgres() -> (
    None
):
    """Overlapping identical calls return one receipt, debit, and dispatch."""
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-upstream-pg-identical-{suffix}"
    idempotency_key = f"partner-upstream-pg-identical-{suffix}"
    executor = PausedUpstreamExecutor()
    _register_paused_upstream(tool_name, executor)
    first_task: asyncio.Task[Any] | None = None
    second_task: asyncio.Task[Any] | None = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            provisioned = await provision_agent_wallet(client)
            permit = await create_tool_permit(
                client,
                wallet_id=provisioned["agent_wallet_id"],
                key_id=provisioned["key_id"],
                tool_name=tool_name,
                idem_key=f"permit-{suffix}",
            )
            body = _upstream_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key=idempotency_key,
                message="same",
            )
            first_task = asyncio.create_task(
                client.post(
                    "/mcp/messages",
                    json=body,
                    headers=provisioned["agent_headers"],
                )
            )
            await asyncio.wait_for(executor.dispatched.wait(), timeout=5)
            second_task = asyncio.create_task(
                client.post(
                    "/mcp/messages",
                    json=body,
                    headers=provisioned["agent_headers"],
                )
            )
            await asyncio.sleep(0.1)
            executor.release.set()
            first, second = await asyncio.wait_for(
                asyncio.gather(first_task, second_task),
                timeout=10,
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["result"] == second.json()["result"]
        receipt_id = first.json()["result"]["receipt"]["receipt_id"]
        record, debits, attempts, receipts = await _load_governed_operation_rows(
            wallet_id=provisioned["agent_wallet_id"],
            idempotency_key=idempotency_key,
        )
        assert len(debits) == 1
        assert len(attempts) == 1
        assert len(receipts) == 1
        assert executor.dispatch_count == 1
        assert len(executor.calls) == 1
        assert executor.calls[0]["invocation_id"] == record.record_id
        assert debits[0].operation_key == record.record_id
        assert attempts[0].ledger_entry_id == debits[0].entry_id
        assert receipts[0].receipt_id == receipt_id
        assert receipts[0].dispatch_attempt_id == attempts[0].attempt_id
    finally:
        executor.release.set()
        pending = [
            task
            for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        get_service_registry().unregister_local(tool_name)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("max_calls", "aggregate_cap", "expected_reason"),
    [
        (1, None, "permit_max_calls_exceeded"),
        (None, 2, "permit_aggregate_value_cap_exceeded"),
    ],
)
async def test_distinct_upstream_requests_cannot_exceed_reserved_permit_authority(
    max_calls: int | None,
    aggregate_cap: int | None,
    expected_reason: str,
) -> None:
    """A receipt-lag window cannot admit a second distinct remote effect."""
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-upstream-pg-authority-{suffix}"
    first_key = f"partner-upstream-pg-authority-first-{suffix}"
    second_key = f"partner-upstream-pg-authority-second-{suffix}"
    executor = PausedUpstreamExecutor()
    _register_paused_upstream(tool_name, executor)
    first_task: asyncio.Task[Any] | None = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            provisioned = await provision_agent_wallet(client)
            permit = await create_tool_permit(
                client,
                wallet_id=provisioned["agent_wallet_id"],
                key_id=provisioned["key_id"],
                tool_name=tool_name,
                max_credits=20,
                idem_key=f"permit-authority-{suffix}",
                max_calls_per_tool=(
                    {tool_name: max_calls} if max_calls is not None else None
                ),
                aggregate_value_cap=aggregate_cap,
            )
            first_task = asyncio.create_task(
                client.post(
                    "/mcp/messages",
                    json=_upstream_call_body(
                        tool_name=tool_name,
                        wallet_id=provisioned["agent_wallet_id"],
                        permit_id=permit["permit_id"],
                        idempotency_key=first_key,
                        message="first",
                    ),
                    headers=provisioned["agent_headers"],
                )
            )
            await asyncio.wait_for(executor.dispatched.wait(), timeout=5)

            denied = await asyncio.wait_for(
                client.post(
                    "/mcp/messages",
                    json=_upstream_call_body(
                        tool_name=tool_name,
                        wallet_id=provisioned["agent_wallet_id"],
                        permit_id=permit["permit_id"],
                        idempotency_key=second_key,
                        message="second",
                    ),
                    headers=provisioned["agent_headers"],
                ),
                timeout=5,
            )
            executor.release.set()
            first = await asyncio.wait_for(first_task, timeout=10)

        assert first.status_code == 200
        assert "result" in first.json()
        assert denied.status_code == 200
        assert "error" in denied.json()
        assert expected_reason in denied.json()["error"]["message"]
        assert executor.dispatch_count == 1
        assert len(executor.calls) == 1

        factory = get_session_factory()
        async with factory() as session:
            attempts = (
                (
                    await session.execute(
                        select(McpDispatchAttemptModel).where(
                            McpDispatchAttemptModel.permit_id == permit["permit_id"]
                        )
                    )
                )
                .scalars()
                .all()
            )
            stored_permit = await session.get(PermitModel, permit["permit_id"])
        assert len(attempts) == 1
        assert stored_permit is not None
        assert stored_permit.spent_credits == Decimal("2")
    finally:
        executor.release.set()
        if first_task is not None and not first_task.done():
            await asyncio.gather(first_task, return_exceptions=True)
        get_service_registry().unregister_local(tool_name)


@pytest.mark.asyncio(loop_scope="session")
async def test_distinct_local_requests_cannot_exceed_call_limit_before_receipt() -> (
    None
):
    """A paused local effect occupies its call slot before a receipt exists."""
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-local-pg-authority-{suffix}"
    first_key = f"partner-local-pg-authority-first-{suffix}"
    second_key = f"partner-local-pg-authority-second-{suffix}"
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    calls: list[str] = []

    async def controlled_local_tool(message: str) -> dict[str, str]:
        calls.append(message)
        if message == "first":
            first_entered.set()
            await release_first.wait()
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name="PostgreSQL Local Concurrency Tool",
        description="Controlled local MCP concurrency test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=controlled_local_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    first_task: asyncio.Task[Any] | None = None
    second_task: asyncio.Task[Any] | None = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            provisioned = await provision_agent_wallet(client)
            permit = await create_tool_permit(
                client,
                wallet_id=provisioned["agent_wallet_id"],
                key_id=provisioned["key_id"],
                tool_name=tool_name,
                max_credits=20,
                idem_key=f"permit-local-authority-{suffix}",
                max_calls_per_tool={tool_name: 1},
            )
            first_body = _upstream_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key=first_key,
                message="first",
            )
            first_task = asyncio.create_task(
                client.post(
                    "/mcp/messages",
                    json=first_body,
                    headers=provisioned["agent_headers"],
                )
            )
            await asyncio.wait_for(first_entered.wait(), timeout=5)
            assert first_task.done() is False

            second_task = asyncio.create_task(
                client.post(
                    "/mcp/messages",
                    json=_upstream_call_body(
                        tool_name=tool_name,
                        wallet_id=provisioned["agent_wallet_id"],
                        permit_id=permit["permit_id"],
                        idempotency_key=second_key,
                        message="second",
                    ),
                    headers=provisioned["agent_headers"],
                )
            )
            denied = await asyncio.wait_for(asyncio.shield(second_task), timeout=5)
            factory = get_session_factory()
            async with factory() as session:
                in_flight_reservations = (
                    (
                        await session.execute(
                            select(PermitCallReservationModel).where(
                                PermitCallReservationModel.permit_id
                                == permit["permit_id"]
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            assert len(in_flight_reservations) == 1
            assert in_flight_reservations[0].state == "consumed"
            assert in_flight_reservations[0].execution_started_at is not None
            release_first.set()
            first = await asyncio.wait_for(first_task, timeout=10)
            replay = await asyncio.wait_for(
                client.post(
                    "/mcp/messages",
                    json=first_body,
                    headers=provisioned["agent_headers"],
                ),
                timeout=5,
            )

        assert first.status_code == 200
        assert "result" in first.json()
        assert denied.status_code == 200
        assert calls == ["first"]
        assert "error" in denied.json(), denied.json()
        assert denied.json()["error"]["message"] == "permit_max_calls_exceeded"
        assert replay.status_code == 200
        assert (
            replay.json()["result"]["receipt"]["receipt_id"]
            == (first.json()["result"]["receipt"]["receipt_id"])
        )
        assert calls == ["first"]
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
        assert stored_permit.spent_credits == Decimal("2")
        assert len(reservations) == 1
        assert reservations[0].state == "consumed"
    finally:
        release_first.set()
        pending = [
            task
            for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        get_service_registry().unregister_local(tool_name)


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_refresh_rotation_creates_one_child_in_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent-token compare-and-swap admits exactly one rotation winner."""
    _require_opted_in_postgres()
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", TEST_JWT_SIGNING_KEY)
    get_settings.cache_clear()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            provisioned = await provision_agent_wallet(client)
            minted = await client.post(
                "/v1/auth/token",
                json={"api_key": provisioned["agent_headers"]["X-API-Key"]},
            )
            assert minted.status_code == 200, minted.text
            parent_token = minted.json()["refresh_token"]
            parent = get_jwt_service().verify_refresh_token(parent_token)

            responses = await asyncio.gather(
                *(
                    client.post(
                        "/v1/auth/refresh",
                        json={"refresh_token": parent_token},
                    )
                    for _ in range(16)
                )
            )

            winners = [
                response for response in responses if response.status_code == 200
            ]
            losers = [response for response in responses if response.status_code == 401]
            assert len(winners) == 1
            assert len(losers) == 15
            assert {response.json()["detail"]["error"] for response in losers} == {
                "revoked_refresh_token"
            }

            child_token = winners[0].json()["refresh_token"]
            child = get_jwt_service().verify_refresh_token(child_token)
            factory = get_session_factory()
            async with factory() as session:
                records = (
                    (
                        await session.execute(
                            select(RefreshTokenModel).where(
                                RefreshTokenModel.wallet_id
                                == provisioned["agent_wallet_id"]
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            assert {record.jti for record in records} == {parent.jti, child.jti}
            assert next(
                record for record in records if record.jti == parent.jti
            ).revoked
            assert not next(
                record for record in records if record.jti == child.jti
            ).revoked

            redeem_child = await client.post(
                "/v1/auth/refresh", json={"refresh_token": child_token}
            )
            assert redeem_child.status_code == 200, redeem_child.text
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_claim_cas_is_exclusive_in_postgres() -> None:
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-dispatch-claim-pg-{suffix}"
    idempotency_key = f"partner-dispatch-claim-pg-{suffix}"
    credits = Decimal("1.5")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        provisioned = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key=f"permit-dispatch-claim-{suffix}",
        )

    request_payload = {
        "tool_name": tool_name,
        "arguments": {"message": suffix},
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
    }
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        operation_kind="upstream_mcp",
    )
    dispatch = get_mcp_dispatch_attempt_service()
    validation, attempt = await dispatch.authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="partner.echo",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=credits,
    )
    assert validation.allowed is True
    assert attempt is not None
    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        operation_key=begun.record_id,
    )
    assert hasattr(charge, "entry_id")
    await dispatch.attach_charge(
        attempt_id=attempt.attempt_id,
        ledger_entry_id=charge.entry_id,
        credits_charged=credits,
    )

    first, second = await asyncio.gather(
        McpDispatchAttemptService().claim_dispatch(attempt.attempt_id),
        McpDispatchAttemptService().claim_dispatch(attempt.attempt_id),
        return_exceptions=True,
    )

    outcomes = (first, second)
    winners = [row for row in outcomes if isinstance(row, McpDispatchAttemptModel)]
    losers = [row for row in outcomes if isinstance(row, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], DispatchClaimUnavailableError)
    assert str(losers[0]) == "dispatch_claim_unavailable"

    factory = get_session_factory()
    async with factory() as session:
        stored = await session.get(McpDispatchAttemptModel, attempt.attempt_id)
        permit_model = await session.get(PermitModel, permit["permit_id"])
        ledger_rows = list(
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.wallet_id == provisioned["agent_wallet_id"],
                        LedgerEntryModel.operation_key == begun.record_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        receipt_rows = list(
            (
                await session.execute(
                    select(ReceiptModel).where(
                        ReceiptModel.idempotency_record_id == begun.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert stored is not None
    assert stored.state == "dispatch_claimed"
    assert stored.dispatch_claim_hash is not None
    assert stored.debit_refunded_at is None
    assert stored.budget_released_at is None
    assert permit_model is not None and permit_model.spent_credits == credits
    assert [row.action for row in ledger_rows] == ["debit"]
    assert receipt_rows == []

    # The same database predicate must also make claim and pre-dispatch
    # compensation mutually exclusive. Exactly one transition may win.
    race_key = f"partner-dispatch-compensation-pg-{suffix}"
    race_payload = {**request_payload, "arguments": {"message": f"race-{suffix}"}}
    race_begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=race_key,
        request_payload=race_payload,
        operation_kind="upstream_mcp",
    )
    race_validation, race_attempt = await dispatch.authorize_reserve_and_prepare(
        idempotency_record_id=race_begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="partner.echo",
        upstream_origin="https://partner.example",
        request_hash=race_begun.request_hash,
        credits_authorized=credits,
    )
    assert race_validation.allowed is True
    assert race_attempt is not None
    race_charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        operation_key=race_begun.record_id,
    )
    assert hasattr(race_charge, "entry_id")
    race_attempt = await dispatch.attach_charge(
        attempt_id=race_attempt.attempt_id,
        ledger_entry_id=race_charge.entry_id,
        credits_charged=credits,
    )

    claim_result, compensation_result = await asyncio.gather(
        McpDispatchAttemptService().claim_dispatch(race_attempt.attempt_id),
        McpDispatchAttemptService().complete_pre_dispatch_failure(
            attempt_id=race_attempt.attempt_id,
            expected_updated_at=race_attempt.updated_at,
            ledger_entry_id=race_charge.entry_id,
            credits_charged=credits,
            result_payload={"error": "failed_refunded"},
            error_code="reconciled_stale_prepared",
            max_result_bytes=4096,
        ),
        return_exceptions=True,
    )

    race_outcomes = (claim_result, compensation_result)
    race_winners = [
        row for row in race_outcomes if isinstance(row, McpDispatchAttemptModel)
    ]
    race_losers = [row for row in race_outcomes if isinstance(row, Exception)]
    assert len(race_winners) == 1
    assert len(race_losers) == 1
    assert isinstance(race_losers[0], DispatchClaimUnavailableError)

    async with factory() as session:
        raced = await session.get(
            McpDispatchAttemptModel,
            race_attempt.attempt_id,
        )
        raced_ledger = list(
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.operation_key == race_begun.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert raced is not None
    assert raced.state in {"dispatch_claimed", "returned_error"}
    assert raced.debit_refunded_at is None
    assert raced.budget_released_at is None
    assert [row.action for row in raced_ledger] == ["debit"]
    if raced.state == "dispatch_claimed":
        assert raced.dispatch_claim_hash is not None
        assert raced.completed_at is None
    else:
        assert raced.dispatch_claim_hash is None
        assert raced.dispatched_at is None
        assert raced.completed_at is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_approval_consumption_and_remote_prepare_are_atomic_in_postgres() -> None:
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-approval-atomic-pg-{suffix}"
    idempotency_key = f"partner-approval-atomic-pg-{suffix}"
    approval_id = f"approval-atomic-pg-{suffix}"
    credits = Decimal("1.5")
    arguments = {"message": suffix}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        provisioned = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key=f"permit-approval-atomic-{suffix}",
            requires_human_approval=True,
        )

    request_payload = {
        "tool_name": tool_name,
        "arguments": arguments,
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
    }
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        operation_kind="upstream_mcp",
    )
    approval_time = utc_now()
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(
                HumanApprovalModel(
                    approval_id=approval_id,
                    wallet_id=provisioned["agent_wallet_id"],
                    permit_id=permit["permit_id"],
                    tool=tool_name,
                    idempotency_key=idempotency_key,
                    request_hash=invoke_request_hash(
                        tool_name,
                        arguments,
                        credits,
                    ),
                    status="approved",
                    simulated=True,
                    requested_at=approval_time,
                    expires_at=approval_time + timedelta(minutes=5),
                    decided_at=approval_time,
                )
            )

    kwargs = {
        "idempotency_record_id": begun.record_id,
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
        "approval_id": approval_id,
        "key_id": provisioned["key_id"],
        "public_tool_id": tool_name,
        "upstream_tool_name": "partner.write",
        "upstream_origin": "https://partner.example",
        "request_hash": begun.request_hash,
        "credits_authorized": credits,
        "arguments": arguments,
    }
    first, second = await asyncio.gather(
        McpDispatchAttemptService().authorize_reserve_and_prepare(**kwargs),
        McpDispatchAttemptService().authorize_reserve_and_prepare(**kwargs),
    )

    assert first[0].allowed is True
    assert second[0].allowed is True
    assert first[1] is not None and second[1] is not None
    assert first[1].attempt_id == second[1].attempt_id
    async with factory() as session:
        approval = await session.get(HumanApprovalModel, approval_id)
        stored_permit = await session.get(PermitModel, permit["permit_id"])
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
    assert approval is not None and approval.status == "consumed"
    assert stored_permit is not None
    assert stored_permit.spent_credits == credits
    assert len(attempts) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_late_approval_cannot_forge_timely_evidence_in_postgres() -> None:
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-approval-clock-pg-{suffix}"
    idempotency_key = f"partner-approval-clock-pg-{suffix}"
    approval_id = f"approval-clock-pg-{suffix}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        provisioned = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key=f"permit-approval-clock-{suffix}",
            requires_human_approval=True,
        )

    now = utc_now()
    approval = HumanApprovalModel(
        approval_id=approval_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool=tool_name,
        idempotency_key=idempotency_key,
        request_hash=invoke_request_hash(tool_name, {}, Decimal("1.5")),
        status="pending",
        simulated=False,
        requested_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            session.add(approval)

    # This detached timestamp would have passed the former worker-authored
    # predicate even though PostgreSQL's clock is already past the deadline.
    approval.status = "approved"
    approval.decided_at = now - timedelta(minutes=9)
    approval.decided_by = "late-reviewer"
    service = HumanApprovalService()

    assert await service._persist_decision(approval) is False
    assert await service._consume(approval_id) is False
    async with factory() as session:
        stored = await session.get(HumanApprovalModel, approval_id)
    assert stored is not None
    assert stored.status == "expired"
    assert stored.decided_at is not None
    assert stored.decided_at >= stored.expires_at


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_dispatch_reconcilers_create_one_signed_audit_in_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two replicas that both observe no audit converge on one signed event."""
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-reconcile-pg-{suffix}"
    idempotency_key = f"partner-reconcile-pg-{suffix}"
    credits = Decimal("1.5")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        provisioned = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key=f"permit-reconcile-{suffix}",
        )

    request_payload = {
        "tool_name": tool_name,
        "arguments": {"message": suffix},
        "wallet_id": provisioned["agent_wallet_id"],
        "permit_id": permit["permit_id"],
    }
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        operation_kind="upstream_mcp",
    )
    dispatch = get_mcp_dispatch_attempt_service()
    validation, attempt = await dispatch.authorize_reserve_and_prepare(
        idempotency_record_id=begun.record_id,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        key_id=provisioned["key_id"],
        public_tool_id=tool_name,
        upstream_tool_name="partner.echo",
        upstream_origin="https://partner.example",
        request_hash=begun.request_hash,
        credits_authorized=credits,
    )
    assert validation.allowed is True
    assert attempt is not None
    charge = await get_agent_money().charge(
        wallet_id=provisioned["agent_wallet_id"],
        service_category=ServiceCategory.AGENT_COMMS,
        units=Decimal("1"),
        request_path=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
        operation_key=begun.record_id,
    )
    assert hasattr(charge, "entry_id")
    await dispatch.attach_charge(
        attempt_id=attempt.attempt_id,
        ledger_entry_id=charge.entry_id,
        credits_charged=credits,
    )
    await dispatch.claim_dispatch(attempt.attempt_id)
    terminal = await dispatch.complete(
        attempt_id=attempt.attempt_id,
        state="succeeded",
        result_payload={
            "content": [{"type": "text", "text": "confirmed"}],
            "isError": False,
        },
        error_code=None,
        max_result_bytes=4096,
    )

    original_find = McpDispatchReconciliationService._find_existing_audit
    both_observed_missing = asyncio.Event()
    missing_observations = 0

    async def pause_after_missing_audit(self, context):  # noqa: ANN001, ANN202
        nonlocal missing_observations
        existing = await original_find(self, context)
        if existing is None:
            missing_observations += 1
            if missing_observations == 2:
                both_observed_missing.set()
            await asyncio.wait_for(both_observed_missing.wait(), timeout=5)
        return existing

    monkeypatch.setattr(
        McpDispatchReconciliationService,
        "_find_existing_audit",
        pause_after_missing_audit,
    )
    first = McpDispatchReconciliationService()
    second = McpDispatchReconciliationService()

    await asyncio.wait_for(
        asyncio.gather(
            first.reconcile_attempt(terminal.attempt_id),
            second.reconcile_attempt(terminal.attempt_id),
        ),
        timeout=10,
    )

    factory = get_session_factory()
    async with factory() as session:
        audits = (
            (
                await session.execute(
                    select(ControlPlaneAuditEventModel).where(
                        ControlPlaneAuditEventModel.request_id == terminal.attempt_id,
                        ControlPlaneAuditEventModel.event == "mcp.invoke",
                    )
                )
            )
            .scalars()
            .all()
        )
        receipts = (
            (
                await session.execute(
                    select(ReceiptModel).where(
                        ReceiptModel.dispatch_attempt_id == terminal.attempt_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert missing_observations == 2
    assert len(audits) == 1
    assert len(receipts) == 1
    assert receipts[0].audit_event_id == audits[0].event_id
    assert audits[0].event_id == f"audit-dsp-{sha256_hex(terminal.attempt_id)[:32]}"


@pytest.mark.asyncio(loop_scope="session")
async def test_conflicting_payload_during_upstream_dispatch_rejects_in_postgres() -> (
    None
):
    """A conflicting payload cannot join or redispatch an in-flight operation."""
    _require_opted_in_postgres()
    suffix = uuid.uuid4().hex[:12]
    tool_name = f"partner-upstream-pg-conflict-{suffix}"
    idempotency_key = f"partner-upstream-pg-conflict-{suffix}"
    executor = PausedUpstreamExecutor()
    _register_paused_upstream(tool_name, executor)
    first_task: asyncio.Task[Any] | None = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            provisioned = await provision_agent_wallet(client)
            permit = await create_tool_permit(
                client,
                wallet_id=provisioned["agent_wallet_id"],
                key_id=provisioned["key_id"],
                tool_name=tool_name,
                idem_key=f"permit-{suffix}",
            )
            first_body = _upstream_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key=idempotency_key,
                message="first",
            )
            first_task = asyncio.create_task(
                client.post(
                    "/mcp/messages",
                    json=first_body,
                    headers=provisioned["agent_headers"],
                )
            )
            await asyncio.wait_for(executor.dispatched.wait(), timeout=5)
            conflict = await asyncio.wait_for(
                client.post(
                    "/mcp/messages",
                    json=_upstream_call_body(
                        tool_name=tool_name,
                        wallet_id=provisioned["agent_wallet_id"],
                        permit_id=permit["permit_id"],
                        idempotency_key=idempotency_key,
                        message="changed",
                    ),
                    headers=provisioned["agent_headers"],
                ),
                timeout=5,
            )
            executor.release.set()
            first = await asyncio.wait_for(first_task, timeout=10)

        assert first.status_code == 200
        assert "result" in first.json()
        assert conflict.status_code == 200
        assert conflict.json()["error"]["message"] == "idempotency_key_reused"
        record, debits, attempts, receipts = await _load_governed_operation_rows(
            wallet_id=provisioned["agent_wallet_id"],
            idempotency_key=idempotency_key,
        )
        assert len(debits) == 1
        assert len(attempts) == 1
        assert len(receipts) == 1
        assert executor.dispatch_count == 1
        assert len(executor.calls) == 1
        assert debits[0].operation_key == record.record_id
        assert (
            receipts[0].receipt_id == (first.json()["result"]["receipt"]["receipt_id"])
        )
    finally:
        executor.release.set()
        if first_task is not None and not first_task.done():
            await asyncio.gather(first_task, return_exceptions=True)
        get_service_registry().unregister_local(tool_name)
