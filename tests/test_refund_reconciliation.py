from __future__ import annotations

import asyncio
from decimal import Decimal
import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, ReceiptModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.audit_chain import verify_audit_chain
from app.services.audit_log import list_audit_events
from app.services.permits import get_permit_service
from app.services.refund_reconciliation import (
    RefundReconciliationError,
    RefundReconciliationService,
)
from app.services.receipts import ReceiptService
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance


async def _create_unrefunded_failure(client: AsyncClient) -> dict[str, Any]:
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    calls = {"count": 0}

    def failing_tool() -> dict[str, Any]:
        calls["count"] += 1
        raise RuntimeError("tool exploded")

    async def failing_refund(self, **_kwargs):  # noqa: ANN001
        raise RuntimeError("refund down")

    tool_name = "operator-reconcile-refund-tool"
    registry.register_local(
        service_id=tool_name,
        name="Operator Reconcile Refund Tool",
        description="Operator refund reconciliation test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=failing_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        max_credits=2,
        idem_key="operator-reconcile-permit-create",
    )
    body = {
        "jsonrpc": "2.0",
        "id": "operator-reconcile-call",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {},
            "mcpContext": {
                "wallet_id": provisioned["agent_wallet_id"],
                "permit_id": permit["permit_id"],
                "idempotency_key": "operator-reconcile-invoke",
            },
        },
    }
    try:
        with patch(
            "app.services.agent_money.AgentMoney.refund_charge",
            failing_refund,
        ):
            response = await client.post(
                "/mcp/messages",
                json=body,
                headers=provisioned["agent_headers"],
            )
    finally:
        registry.unregister_local(tool_name)

    assert response.status_code == 200
    data = response.json()["error"]["data"]
    assert data["receipt"]["outcome"] == "failed_unrefunded"
    assert Decimal(data["receipt"]["credits_charged"]) == Decimal("2")
    assert data["refund_reconciliation"]["status"] == "pending"
    pending_audits = await list_audit_events(
        event="mcp.refund_reconciliation.pending",
        wallet_id=provisioned["agent_wallet_id"],
    )
    assert len(pending_audits) == 1
    assert pending_audits[0].metadata == {
        "receipt_id": data["receipt"]["receipt_id"],
        "permit_id": permit["permit_id"],
        "ledger_entry_id": data["receipt"]["ledger_entry_id"],
        "credits": "2.0",
        "status": "pending",
    }
    assert pending_audits[0].chain_hash
    assert pending_audits[0].signature
    return {
        "provisioned": provisioned,
        "permit": permit,
        "request": body,
        "response": response,
        "receipt": data["receipt"],
        "calls": calls,
    }


@pytest.mark.anyio
async def test_refund_reconciliation_is_bootstrap_admin_only(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    agent_headers = case["provisioned"]["agent_headers"]

    listing = await client.get(
        "/v1/receipts/reconciliation/refunds",
        headers=agent_headers,
    )
    retry = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers=agent_headers,
    )

    assert listing.status_code == 403
    assert listing.json()["detail"]["error"] == "admin_access_denied"
    assert retry.status_code == 403
    assert retry.json()["detail"]["error"] == "admin_access_denied"


@pytest.mark.anyio
async def test_refund_reconciliation_retries_exactly_once_and_preserves_agent_replay(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]
    permit_id = case["permit"]["permit_id"]

    pending = await client.get(
        "/v1/receipts/reconciliation/refunds",
        headers=BOOTSTRAP_HEADERS,
    )
    assert pending.status_code == 200
    assert pending.json()["total"] == 1
    assert pending.json()["items"][0]["status"] == "pending"

    # The periodic stale-budget reconciler must preserve a real debit while
    # its failed refund remains pending, even after the permit is revoked.
    await get_permit_service().revoke_permit(permit_id)
    assert await get_permit_service().reconcile_budgets(idle_seconds=0) == 0
    pending_permit = await get_permit_service().get_permit(permit_id)
    assert pending_permit is not None
    assert pending_permit.spent_credits == 2

    first, concurrent_replay = await asyncio.gather(
        client.post(
            f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "operator-retry-a"},
        ),
        client.post(
            f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "operator-retry-b"},
        ),
    )
    assert first.status_code == 200
    assert concurrent_replay.status_code == 200
    responses = [first.json(), concurrent_replay.json()]
    assert sorted(response["replayed"] for response in responses) == [False, True]
    assert {response["item"]["status"] for response in responses} == {"resolved"}
    assert len({response["item"]["refund_entry_id"] for response in responses}) == 1

    duplicate = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "operator-retry-c"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["replayed"] is True

    resolved_listing = await client.get(
        "/v1/receipts/reconciliation/refunds?status=resolved",
        headers=BOOTSTRAP_HEADERS,
    )
    assert resolved_listing.status_code == 200
    assert resolved_listing.json()["total"] == 1
    assert resolved_listing.json()["items"][0]["receipt_id"] == receipt_id

    resolved_audits = await list_audit_events(
        event="mcp.refund_reconciliation.resolved",
        wallet_id=wallet_id,
    )
    assert len(resolved_audits) == 3
    assert {event.metadata["receipt_id"] for event in resolved_audits} == {receipt_id}
    assert {event.metadata["ledger_entry_id"] for event in resolved_audits} == {
        case["receipt"]["ledger_entry_id"]
    }
    assert all(event.chain_hash and event.signature for event in resolved_audits)

    wallet = await client.get(
        f"/v1/billing/wallets/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert Decimal(wallet.json()["balance_exact"]) == Decimal("1000")
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    assert permit.spent_credits == 0
    # Once the correlated refund exists, failed_unrefunded no longer counts as
    # consumed budget during the same periodic reconciliation.
    assert await get_permit_service().reconcile_budgets(idle_seconds=0) == 0
    reconciled_permit = await get_permit_service().get_permit(permit_id)
    assert reconciled_permit is not None
    assert reconciled_permit.spent_credits == 0

    ledger = await client.get(
        f"/v1/billing/ledger/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    entries = [
        entry
        for entry in ledger.json()["entries"]
        if "operator-reconcile-refund-tool" in entry["description"]
        or entry["entry_id"] == duplicate.json()["item"]["refund_entry_id"]
    ]
    assert sorted(entry["action"] for entry in entries) == ["debit", "refund"]
    refund_entry = next(entry for entry in entries if entry["action"] == "refund")
    refund_metadata = refund_entry["metadata"]["refund_reconciliation"]
    assert Decimal(refund_metadata.pop("credits_released")) == Decimal("2")
    assert refund_metadata == {
        "record_id": duplicate.json()["item"]["record_id"],
        "receipt_id": receipt_id,
        "permit_id": permit_id,
        "status": "resolved",
    }

    verified_receipt = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt_id},
        headers=case["provisioned"]["agent_headers"],
    )
    assert verified_receipt.status_code == 200
    assert verified_receipt.json()["valid"] is True
    assert verified_receipt.json()["receipt"]["outcome"] == "failed_unrefunded"
    assert Decimal(verified_receipt.json()["receipt"]["credits_charged"]) == Decimal(
        "2"
    )

    replay = await client.post(
        "/mcp/messages",
        json=case["request"],
        headers=case["provisioned"]["agent_headers"],
    )
    assert replay.status_code == 200
    replay_data = replay.json()["error"]["data"]
    assert replay_data["receipt"]["receipt_id"] == receipt_id
    assert replay_data["refund_reconciliation"]["status"] == "resolved"
    assert case["calls"]["count"] == 1
    chain = await verify_audit_chain(wallet_id=wallet_id)
    assert chain.valid is True


@pytest.mark.anyio
async def test_forged_resolved_reconciliation_without_refund_fails_closed(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]
    permit_id = case["permit"]["permit_id"]

    # A legitimate pending replay is read-only and remains visible to the
    # agent while operator repair has not happened.
    pending_replay = await client.post(
        "/mcp/messages",
        json=case["request"],
        headers=case["provisioned"]["agent_headers"],
    )
    assert pending_replay.status_code == 200
    assert (
        pending_replay.json()["error"]["data"]["refund_reconciliation"]["status"]
        == "pending"
    )

    # Simulate a corrupted or forged work-item transition without the exact
    # correlated ledger refund that is required to substantiate resolution.
    factory = get_session_factory()
    async with factory() as session:
        record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.response_reference == receipt_id
                )
            )
        ).scalar_one()
        payload = json.loads(record.response_json or "{}")
        payload["refund_reconciliation"]["status"] = "resolved"
        payload["refund_reconciliation"]["resolved_at"] = "2026-08-05T12:00:00+00:00"
        record.response_json = json.dumps(payload)
        session.add(record)
        await session.commit()
        forged_response_json = record.response_json

    replay = await client.post(
        "/mcp/messages",
        json=case["request"],
        headers=case["provisioned"]["agent_headers"],
    )
    assert replay.status_code == 200
    assert replay.json()["error"]["message"] == (
        "refund_reconciliation_resolution_invalid"
    )
    assert "refund_reconciliation" not in replay.json()["error"].get("data", {})

    listing = await client.get(
        "/v1/receipts/reconciliation/refunds?status=resolved",
        headers=BOOTSTRAP_HEADERS,
    )
    assert listing.status_code == 409
    assert listing.json()["detail"] == "refund_reconciliation_resolution_invalid"
    with pytest.raises(
        RefundReconciliationError,
        match="refund_reconciliation_resolution_invalid",
    ):
        await RefundReconciliationService().get_item(receipt_id)

    wallet = await client.get(
        f"/v1/billing/wallets/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert Decimal(wallet.json()["balance_exact"]) == Decimal("998")
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    assert permit.spent_credits == 2
    ledger = await client.get(
        f"/v1/billing/ledger/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert all(entry["action"] != "refund" for entry in ledger.json()["entries"])
    assert case["calls"]["count"] == 1
    async with factory() as session:
        unchanged_record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.response_reference == receipt_id
                )
            )
        ).scalar_one()
        assert unchanged_record.response_json == forged_response_json


@pytest.mark.anyio
async def test_resolved_reconciliation_reads_require_signed_receipt(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    resolved = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers=BOOTSTRAP_HEADERS,
    )
    assert resolved.status_code == 200

    factory = get_session_factory()
    async with factory() as session:
        receipt = await session.get(ReceiptModel, receipt_id)
        assert receipt is not None
        receipt.request_hash = "0" * 64
        session.add(receipt)
        await session.commit()

    listing = await client.get(
        "/v1/receipts/reconciliation/refunds?status=resolved",
        headers=BOOTSTRAP_HEADERS,
    )
    assert listing.status_code == 409
    assert listing.json()["detail"] == "refund_reconciliation_receipt_invalid"
    with pytest.raises(
        RefundReconciliationError,
        match="refund_reconciliation_receipt_invalid",
    ):
        await RefundReconciliationService().get_item(receipt_id)

    replay = await client.post(
        "/mcp/messages",
        json=case["request"],
        headers=case["provisioned"]["agent_headers"],
    )
    assert replay.status_code == 200
    assert replay.json()["error"]["message"] == (
        "refund_reconciliation_resolution_invalid"
    )
    assert "refund_reconciliation" not in replay.json()["error"].get("data", {})


@pytest.mark.anyio
async def test_failed_operator_refund_retry_stays_pending(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]
    permit_id = case["permit"]["permit_id"]

    with patch.object(
        RefundReconciliationService,
        "_apply_refund",
        side_effect=RuntimeError("database write failed"),
    ):
        failed = await client.post(
            f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
            headers=BOOTSTRAP_HEADERS,
        )

    assert failed.status_code == 503
    assert failed.json()["detail"] == "refund_reconciliation_failed"
    pending = await client.get(
        "/v1/receipts/reconciliation/refunds",
        headers=BOOTSTRAP_HEADERS,
    )
    assert pending.json()["total"] == 1
    assert pending.json()["items"][0]["status"] == "pending"

    wallet = await client.get(
        f"/v1/billing/wallets/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert Decimal(wallet.json()["balance_exact"]) == Decimal("998")
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    assert permit.spent_credits == 2
    failed_audits = await list_audit_events(
        event="mcp.refund_reconciliation.failed",
        wallet_id=wallet_id,
    )
    assert len(failed_audits) == 1
    assert failed_audits[0].metadata["receipt_id"] == receipt_id
    assert (
        failed_audits[0].metadata["ledger_entry_id"]
        == case["receipt"]["ledger_entry_id"]
    )
    assert failed_audits[0].chain_hash
    assert failed_audits[0].signature


@pytest.mark.anyio
async def test_cross_linked_refund_reconciliation_fails_closed(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]
    permit_id = case["permit"]["permit_id"]

    factory = get_session_factory()
    async with factory() as session:
        record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.response_reference == receipt_id
                )
            )
        ).scalar_one()
        payload = json.loads(record.response_json or "{}")
        payload["refund_reconciliation"]["permit_id"] = "permit-cross-linked"
        record.response_json = json.dumps(payload)
        session.add(record)
        await session.commit()

    rejected = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers=BOOTSTRAP_HEADERS,
    )
    rejected_listing = await client.get(
        "/v1/receipts/reconciliation/refunds",
        headers=BOOTSTRAP_HEADERS,
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "refund_reconciliation_linkage_invalid"
    assert rejected_listing.status_code == 409
    assert rejected_listing.json()["detail"] == (
        "refund_reconciliation_linkage_invalid"
    )

    wallet = await client.get(
        f"/v1/billing/wallets/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert Decimal(wallet.json()["balance_exact"]) == Decimal("998")
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    assert permit.spent_credits == 2
    ledger = await client.get(
        f"/v1/billing/ledger/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert all(entry["action"] != "refund" for entry in ledger.json()["entries"])


@pytest.mark.anyio
async def test_pending_receipt_and_work_item_roll_back_together(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    original_receipt_id = case["receipt"]["receipt_id"]
    ledger_entry_id = case["receipt"]["ledger_entry_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]

    factory = get_session_factory()
    async with factory() as session:
        record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.response_reference == original_receipt_id
                )
            )
        ).scalar_one()
        receipt = await session.get(ReceiptModel, original_receipt_id)
        assert receipt is not None
        record_endpoint = record.endpoint
        await session.delete(receipt)
        record.response_reference = None
        record.response_json = None
        session.add(record)
        await session.commit()

    original_create = ReceiptService.create_receipt

    async def fail_after_receipt_flush(self, **kwargs):  # noqa: ANN001
        await original_create(self, **kwargs)
        raise RuntimeError("crash after receipt flush")

    service = RefundReconciliationService()
    with patch.object(ReceiptService, "create_receipt", fail_after_receipt_flush):
        with pytest.raises(RuntimeError, match="crash after receipt flush"):
            await service.create_pending(
                wallet_id=wallet_id,
                endpoint=record_endpoint,
                idempotency_key="operator-reconcile-invoke",
                permit_id=case["permit"]["permit_id"],
                key_id=case["provisioned"]["key_id"],
                tool_name="operator-reconcile-refund-tool",
                request_payload=case["request"],
                ledger_entry_id=ledger_entry_id,
                credits_authorized=Decimal("2"),
                credits_charged=Decimal("2"),
                audit_event_id=None,
                reason="refund_failed",
            )

    async with factory() as session:
        record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.ledger_entry_id == ledger_entry_id
                )
            )
        ).scalar_one()
        receipts = (
            (
                await session.execute(
                    select(ReceiptModel).where(
                        ReceiptModel.ledger_entry_id == ledger_entry_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert receipts == []
    assert record.response_reference is None
    assert record.response_json is None


@pytest.mark.anyio
async def test_lost_refund_ack_releases_budget_without_double_refund(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    ledger_entry_id = case["receipt"]["ledger_entry_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]
    permit_id = case["permit"]["permit_id"]

    # Simulate BillingEngine's deterministic refund commit succeeding while
    # the caller loses the acknowledgement and records failed_unrefunded.
    existing_refund = await get_agent_money().refund_charge(
        wallet_id=wallet_id,
        charge_entry_id=ledger_entry_id,
        description="Committed refund with lost acknowledgement",
    )
    assert existing_refund.entry_id == f"refund-{ledger_entry_id}"

    # A background budget sweep must not release a still-pending work item;
    # the operator transaction remains the exact-once release marker.
    await get_permit_service().revoke_permit(permit_id)
    assert await get_permit_service().reconcile_budgets(idle_seconds=0) == 0
    pending_permit = await get_permit_service().get_permit(permit_id)
    assert pending_permit is not None
    assert pending_permit.spent_credits == 2

    resolved = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers=BOOTSTRAP_HEADERS,
    )
    replay = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "different-key"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    wallet = await client.get(
        f"/v1/billing/wallets/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert Decimal(wallet.json()["balance_exact"]) == Decimal("1000")
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    assert permit.spent_credits == 0
    ledger = await client.get(
        f"/v1/billing/ledger/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    refunds = [
        entry
        for entry in ledger.json()["entries"]
        if entry["action"] == "refund"
        and entry["entry_id"] == f"refund-{ledger_entry_id}"
    ]
    assert len(refunds) == 1


@pytest.mark.anyio
async def test_tampered_signed_receipt_cannot_authorize_refund(
    client,
    clean_database,
):
    case = await _create_unrefunded_failure(client)
    receipt_id = case["receipt"]["receipt_id"]
    wallet_id = case["provisioned"]["agent_wallet_id"]
    permit_id = case["permit"]["permit_id"]

    factory = get_session_factory()
    async with factory() as session:
        receipt = await session.get(ReceiptModel, receipt_id)
        assert receipt is not None
        receipt.request_hash = "0" * 64
        session.add(receipt)
        await session.commit()

    rejected = await client.post(
        f"/v1/receipts/reconciliation/refunds/{receipt_id}/retry",
        headers=BOOTSTRAP_HEADERS,
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "refund_reconciliation_receipt_invalid"

    wallet = await client.get(
        f"/v1/billing/wallets/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert Decimal(wallet.json()["balance_exact"]) == Decimal("998")
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    assert permit.spent_credits == 2
    ledger = await client.get(
        f"/v1/billing/ledger/{wallet_id}",
        headers=case["provisioned"]["agent_headers"],
    )
    assert all(entry["action"] != "refund" for entry in ledger.json()["entries"])
