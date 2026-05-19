from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_governed_mcp_invoke_returns_receipt_and_replay_does_not_double_charge(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def trust_echo(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id="trust-echo",
        name="Trust Echo",
        description="Governed trust test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=trust_echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="trust-echo",
        )
        body = {
            "jsonrpc": "2.0",
            "id": "trust-call-1",
            "method": "tools/call",
            "params": {
                "name": "trust-echo",
                "arguments": {"message": "hello"},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "trust-invoke-1",
                },
            },
        }
        first = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
        assert first.status_code == 200
        first_payload = first.json()
        receipt = first_payload["result"]["receipt"]
        assert receipt["permit_id"] == permit["permit_id"]
        assert receipt["ledger_entry_id"]
        assert receipt["outcome"] == "success"

        replay = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
        assert replay.status_code == 200
        assert replay.json()["result"]["receipt"]["receipt_id"] == receipt["receipt_id"]

        ledger_resp = await client.get(
            f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
            headers=provisioned["agent_headers"],
        )
        debits = [
            entry for entry in ledger_resp.json()["entries"]
            if entry["service_category"] == "agent_comms"
            and "trust-echo" in entry["description"]
        ]
        assert len(debits) == 1
    finally:
        registry.unregister_local("trust-echo")


@pytest.mark.anyio
async def test_governed_mcp_requires_idempotency_key(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    registry.register_local(
        service_id="missing-idem-tool",
        name="Missing Idempotency Tool",
        description="Governed trust test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="missing-idem-tool",
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "trust-call-2",
                "method": "tools/call",
                "params": {
                    "name": "missing-idem-tool",
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local("missing-idem-tool")
    assert resp.status_code == 200
    assert resp.json()["error"]["message"] == "idempotency_key_required"


@pytest.mark.anyio
async def test_out_of_scope_governed_mcp_denial_returns_receipt(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    registry.register_local(
        service_id="blocked-trust-tool",
        name="Blocked Trust Tool",
        description="Governed trust denial test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="allowed-trust-tool",
        idem_key="permit-denial-create-1",
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "trust-denial-1",
                "method": "tools/call",
                "params": {
                    "name": "blocked-trust-tool",
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "trust-denial-invoke-1",
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local("blocked-trust-tool")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["error"]["message"] == "permit_tool_not_allowed"
    receipt = payload["error"]["data"]["receipt"]
    assert receipt["permit_id"] == permit["permit_id"]
    assert receipt["outcome"] == "denied"
    assert receipt["ledger_entry_id"] is None
    assert receipt["credits_charged"] == "0"
