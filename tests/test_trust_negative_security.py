"""Negative-path security invariants for the governed invocation pipeline.

These cover the gaps not already exercised elsewhere:
- an expired permit is denied at invocation time (no charge),
- a permit whose budget is too small is denied (no charge),
- a receipt stripped of its signature fails verification.

(Wrong-wallet, wrong-tool, missing-idempotency-key, replay-with-changed-payload,
tampered-receipt, and tampered-audit cases live in test_mcp_trust*.py,
test_idempotency.py, test_receipts.py, and test_audit_chain.py.)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import PermitModel, ReceiptModel
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


def _register_tool(tool_name: str, credits_per_unit: float = 2.0) -> None:
    get_service_registry().register_local(
        service_id=tool_name,
        name=tool_name,
        description="negative-security test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda message="ok": {"message": message},
        credits_per_unit=credits_per_unit,
        unit_name="call",
    )


def _mcp_call(wallet_id: str, permit_id: str, tool_name: str, idem: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": idem,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": "hi"},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idem,
            },
        },
    }


async def _ledger_debits(client, provisioned, tool_name) -> list:
    ledger = await client.get(
        f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
        headers=provisioned["agent_headers"],
    )
    return [
        entry
        for entry in ledger.json()["entries"]
        if entry["service_category"] == "agent_comms"
        and tool_name in entry.get("description", "")
    ]


@pytest.mark.anyio
async def test_expired_permit_is_denied_without_charge(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool_name = "expired-permit-tool"
    _register_tool(tool_name)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
        )

        # Force the permit into the past after creation (creation rejects
        # already-expired permits, so we expire a previously-valid one).
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(PermitModel).where(
                    PermitModel.permit_id == permit["permit_id"]
                )
            )
            model = result.scalar_one()
            model.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            session.add(model)
            await session.commit()

        resp = await client.post(
            "/mcp/messages",
            json=_mcp_call(
                provisioned["agent_wallet_id"],
                permit["permit_id"],
                tool_name,
                "expired-invoke-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        error = resp.json()["error"]
        assert error["message"] == "permit_expired"
        assert await _ledger_debits(client, provisioned, tool_name) == []
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_revoked_permit_is_denied_without_charge(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool_name = "revoked-permit-tool"
    _register_tool(tool_name)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
        )
        revoke = await client.post(
            f"/v1/permits/{permit['permit_id']}/revoke",
            headers={"X-API-Key": "test-key"},
        )
        assert revoke.status_code == 200

        resp = await client.post(
            "/mcp/messages",
            json=_mcp_call(
                provisioned["agent_wallet_id"],
                permit["permit_id"],
                tool_name,
                "revoked-invoke-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        error = resp.json()["error"]
        assert error["message"] == "permit_revoked"
        # A signed denial receipt is still issued, with no ledger charge.
        assert error["data"]["receipt"]["outcome"] == "denied"
        assert error["data"]["receipt"]["ledger_entry_id"] is None
        assert await _ledger_debits(client, provisioned, tool_name) == []
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_budget_exceeded_permit_is_denied_without_charge(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool_name = "budget-tool"
    _register_tool(tool_name, credits_per_unit=2.0)
    try:
        # Tool costs 2 credits; cap the permit below that so the very first
        # call exceeds the bounded budget.
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            max_credits=1,
        )

        resp = await client.post(
            "/mcp/messages",
            json=_mcp_call(
                provisioned["agent_wallet_id"],
                permit["permit_id"],
                tool_name,
                "budget-invoke-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        error = resp.json()["error"]
        assert error["message"] == "permit_budget_exceeded"
        assert await _ledger_debits(client, provisioned, tool_name) == []
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_unsigned_receipt_fails_verification(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool_name = "unsigned-receipt-tool"
    _register_tool(tool_name)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
        )
        resp = await client.post(
            "/mcp/messages",
            json=_mcp_call(
                provisioned["agent_wallet_id"],
                permit["permit_id"],
                tool_name,
                "unsigned-invoke-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        receipt_id = resp.json()["result"]["receipt"]["receipt_id"]

        # Strip the signature from the stored receipt: an unsigned receipt
        # must not verify.
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(ReceiptModel).where(ReceiptModel.receipt_id == receipt_id)
            )
            model = result.scalar_one()
            model.signature = ""
            session.add(model)
            await session.commit()

        valid, reason, _ = await get_receipt_service().verify_receipt(receipt_id)
        assert valid is False
        assert reason == "receipt_signature_invalid"
    finally:
        get_service_registry().unregister_local(tool_name)
