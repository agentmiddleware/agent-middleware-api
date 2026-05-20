from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel, ReceiptModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.receipts import get_receipt_service
from app.services.service_registry import get_service_registry
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


def _register_echo_tool(tool_name: str) -> None:
    def echo(message: str = "ok") -> dict:
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name=f"Evidence test {tool_name}",
        description="Receipt evidence test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=2.0,
        unit_name="call",
    )


async def _create_governed_receipt(
    client: AsyncClient,
    *,
    provisioned: dict,
    tool_name: str,
    idem_key: str,
) -> tuple[dict, dict]:
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool_name,
        idem_key=f"{idem_key}-permit",
    )
    response = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": f"{idem_key}-call",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"message": "hello"},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": idem_key,
                },
            },
        },
        headers=provisioned["agent_headers"],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["isError"] is False
    return permit, payload["result"]["receipt"]


@pytest.mark.anyio
async def test_receipt_evidence_links_governed_mcp_artifacts(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    tool_name = "receipt-evidence-tool"
    registry = get_service_registry()
    _register_echo_tool(tool_name)
    try:
        permit, receipt = await _create_governed_receipt(
            client,
            provisioned=provisioned,
            tool_name=tool_name,
            idem_key="receipt-evidence-success",
        )
        evidence_resp = await client.get(
            f"/v1/receipts/{receipt['receipt_id']}/evidence",
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local(tool_name)

    assert evidence_resp.status_code == 200
    evidence = evidence_resp.json()
    assert evidence["valid"] is True
    assert evidence["permit"]["permit_id"] == permit["permit_id"]
    assert evidence["receipt"]["receipt_id"] == receipt["receipt_id"]
    assert evidence["audit_event"]["event"] == "mcp.invoke"
    assert evidence["ledger_entry"]["entry_id"] == receipt["ledger_entry_id"]

    checks = {check["name"]: check for check in evidence["checks"]}
    for check_name in (
        "wallet_access",
        "receipt_signature",
        "permit_signature",
        "permit_wallet_binding",
        "permit_tool_scope",
        "audit_event_linkage",
        "audit_chain",
        "ledger_linkage",
    ):
        assert checks[check_name]["status"] == "passed"


@pytest.mark.anyio
async def test_receipt_evidence_denies_cross_wallet_access(
    client,
    clean_database,
):
    wallet_a = await provision_agent_wallet(client)
    wallet_b = await provision_agent_wallet(client)
    tool_name = "receipt-evidence-cross-wallet"
    registry = get_service_registry()
    _register_echo_tool(tool_name)
    try:
        _, receipt = await _create_governed_receipt(
            client,
            provisioned=wallet_a,
            tool_name=tool_name,
            idem_key="receipt-evidence-cross-wallet",
        )
        response = await client.get(
            f"/v1/receipts/{receipt['receipt_id']}/evidence",
            headers=wallet_b["agent_headers"],
        )
    finally:
        registry.unregister_local(tool_name)

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "wallet_access_denied"


@pytest.mark.anyio
async def test_receipt_evidence_detects_ledger_tampering(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    tool_name = "receipt-evidence-ledger-tamper"
    registry = get_service_registry()
    _register_echo_tool(tool_name)
    try:
        _, receipt = await _create_governed_receipt(
            client,
            provisioned=provisioned,
            tool_name=tool_name,
            idem_key="receipt-evidence-ledger-tamper",
        )
    finally:
        registry.unregister_local(tool_name)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(LedgerEntryModel).where(
                LedgerEntryModel.entry_id == receipt["ledger_entry_id"]
            )
        )
        entry = result.scalar_one()
        entry.amount = Decimal("-999")
        session.add(entry)
        await session.commit()

    evidence_resp = await client.get(
        f"/v1/receipts/{receipt['receipt_id']}/evidence",
        headers=provisioned["agent_headers"],
    )

    assert evidence_resp.status_code == 200
    evidence = evidence_resp.json()
    assert evidence["valid"] is False
    checks = {check["name"]: check for check in evidence["checks"]}
    assert checks["ledger_linkage"]["status"] == "failed"
    assert checks["ledger_linkage"]["reason"] == "ledger_amount_mismatch"


@pytest.mark.anyio
async def test_receipt_evidence_does_not_expose_cross_wallet_artifacts(
    client,
    clean_database,
):
    wallet_a = await provision_agent_wallet(client)
    wallet_b = await provision_agent_wallet(client)
    tool_a = "receipt-evidence-wallet-a"
    tool_b = "receipt-evidence-wallet-b"
    registry = get_service_registry()
    _register_echo_tool(tool_a)
    _register_echo_tool(tool_b)
    try:
        _, receipt_a = await _create_governed_receipt(
            client,
            provisioned=wallet_a,
            tool_name=tool_a,
            idem_key="receipt-evidence-wallet-a",
        )
        _, receipt_b = await _create_governed_receipt(
            client,
            provisioned=wallet_b,
            tool_name=tool_b,
            idem_key="receipt-evidence-wallet-b",
        )
    finally:
        registry.unregister_local(tool_a)
        registry.unregister_local(tool_b)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ReceiptModel).where(
                ReceiptModel.receipt_id == receipt_a["receipt_id"]
            )
        )
        model = result.scalar_one()
        model.permit_id = receipt_b["permit_id"]
        model.audit_event_id = receipt_b["audit_event_id"]
        model.ledger_entry_id = receipt_b["ledger_entry_id"]
        session.add(model)
        await session.commit()

    evidence_resp = await client.get(
        f"/v1/receipts/{receipt_a['receipt_id']}/evidence",
        headers=wallet_a["agent_headers"],
    )

    assert evidence_resp.status_code == 200
    evidence = evidence_resp.json()
    assert evidence["valid"] is False
    assert evidence["permit"] is None
    assert evidence["audit_event"] is None
    assert evidence["ledger_entry"] is None

    checks = {check["name"]: check for check in evidence["checks"]}
    assert checks["permit_exists"]["status"] == "failed"
    assert checks["audit_event_linkage"]["status"] == "failed"
    assert checks["audit_event_linkage"]["reason"] == "audit_event_not_found"
    assert checks["ledger_linkage"]["status"] == "failed"
    assert checks["ledger_linkage"]["reason"] == "ledger_not_found"
