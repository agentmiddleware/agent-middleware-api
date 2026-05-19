from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import ReceiptModel
from app.main import app
from app.services.receipts import get_receipt_service
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_receipt_signature_verifies_and_detects_tampering(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="receipt-tool",
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="receipt-tool",
        request_payload={"message": "before"},
        response_payload={"message": "after"},
        ledger_entry_id=None,
        credits_authorized=Decimal("2"),
        credits_charged=Decimal("0"),
        outcome="denied",
        audit_event_id=None,
    )

    verify_resp = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt.receipt_id},
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ReceiptModel).where(ReceiptModel.receipt_id == receipt.receipt_id)
        )
        model = result.scalar_one()
        model.outcome = "success"
        session.add(model)
        await session.commit()

    tampered_resp = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt.receipt_id},
        headers=provisioned["agent_headers"],
    )
    assert tampered_resp.status_code == 200
    assert tampered_resp.json()["valid"] is False
    assert tampered_resp.json()["reason"] == "receipt_signature_invalid"
