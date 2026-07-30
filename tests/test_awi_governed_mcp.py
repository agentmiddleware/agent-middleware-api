"""Always-governed AWI MCP tools must require permits even in legacy mode."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import mcp_phase9_tools
from app.services.mcp_phase9_tools import (
    ALWAYS_GOVERNED_AWI_TOOLS,
    MCP_PHASE9_TOOLS,
)
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _reregister_phase9():
    registry = get_service_registry()
    for tool in MCP_PHASE9_TOOLS:
        registry.unregister_local(tool["service_id"])
    mcp_phase9_tools._registered = False
    mcp_phase9_tools.ensure_phase9_registered()


@pytest.fixture(autouse=True)
def _fresh_phase9_tools():
    _reregister_phase9()
    yield


def test_always_governed_tools_are_registered_with_require_permit():
    registry = get_service_registry()
    for tool_id in ALWAYS_GOVERNED_AWI_TOOLS:
        record = registry.get_local(tool_id)
        assert record is not None, tool_id
        assert record.get("require_permit") is True


@pytest.mark.anyio
async def test_manifest_annotates_require_permit(client):
    resp = await client.get("/mcp/tools.json")
    assert resp.status_code == 200
    by_name = {t["name"]: t for t in resp.json()["tools"]}
    for tool_id in ALWAYS_GOVERNED_AWI_TOOLS:
        assert by_name[tool_id]["annotations"]["requirePermit"] is True


@pytest.mark.anyio
async def test_awi_passkey_challenge_denied_without_permit_in_legacy_mode(
    client, clean_database
):
    """Even with ALLOW_LEGACY_UNPERMITTED_MCP, this tool requires a permit."""
    provisioned = await provision_agent_wallet(client)
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": "no-permit",
            "method": "tools/call",
            "params": {
                "name": "awi_passkey_challenge",
                "arguments": {
                    "session_id": "sess-1",
                    "action": "checkout",
                },
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                },
            },
        },
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"]["message"] == "permit_required"


@pytest.mark.anyio
async def test_awi_rag_query_succeeds_with_permit_and_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-rag-1",
    )
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": "rag-governed",
            "method": "tools/call",
            "params": {
                "name": "awi_rag_query",
                "arguments": {
                    "query": "laptops",
                    "top_k": 3,
                },
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "awi-rag-governed-1",
                },
            },
        },
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "error" not in body, body
    result = body["result"]
    receipt = result["receipt"]
    assert receipt["permit_id"] == permit["permit_id"]
    assert receipt["outcome"] == "success"
    assert receipt["ledger_entry_id"]
