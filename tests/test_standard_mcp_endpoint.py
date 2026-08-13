"""Standard MCP endpoint (POST /mcp): SDK-owned lifecycle, gating, auto-permits.

The protocol surface (initialize, version negotiation, notifications, ping,
JSON-RPC framing and errors) is owned by the official MCP SDK; these tests
pin the trust-plane contract layered on top of it — auth gating, origin
validation, server-minted permits, exactly-once replay, and signed receipts.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.types import LATEST_PROTOCOL_VERSION

from app.core.config import get_settings
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.mcp_generator import McpGenerator
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet

# The SDK's streamable HTTP transport requires an explicit Accept header.
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
BOOTSTRAP_MCP_HEADERS = {**BOOTSTRAP_HEADERS, **MCP_HEADERS}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def standard_mcp_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "false")
    get_settings.cache_clear()


def _rpc(method: str, request_id: int | None = 1, params: dict | None = None) -> dict:
    body: dict = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if request_id is not None:
        body["id"] = request_id
    return body


def _initialize(protocol_version: str = "2025-06-18") -> dict:
    return _rpc(
        "initialize",
        params={
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.0"},
        },
    )


@pytest.mark.anyio
async def test_endpoint_disabled_by_default(client):
    resp = await client.post("/mcp", json=_initialize(), headers=BOOTSTRAP_MCP_HEADERS)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_endpoint_requires_credentials(client, standard_mcp_enabled):
    resp = await client.post("/mcp", json=_initialize(), headers=MCP_HEADERS)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_initialize_negotiates_requested_protocol(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp",
        json=_initialize("2025-03-26"),
        headers=BOOTSTRAP_MCP_HEADERS,
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == McpGenerator.MANIFEST_NAME


@pytest.mark.anyio
async def test_initialize_unsupported_version_offers_latest(
    client, standard_mcp_enabled
):
    resp = await client.post(
        "/mcp",
        json=_initialize("1999-01-01"),
        headers=BOOTSTRAP_MCP_HEADERS,
    )
    assert resp.json()["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_notifications_are_accepted_without_reply(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp",
        json=_rpc("notifications/initialized", request_id=None),
        headers=BOOTSTRAP_MCP_HEADERS,
    )
    assert resp.status_code == 202
    assert resp.content == b""


@pytest.mark.anyio
async def test_ping_returns_empty_result(client, standard_mcp_enabled):
    resp = await client.post("/mcp", json=_rpc("ping"), headers=BOOTSTRAP_MCP_HEADERS)
    assert resp.json()["result"] == {}


@pytest.mark.anyio
async def test_tools_list_returns_tools_array(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp", json=_rpc("tools/list"), headers=BOOTSTRAP_MCP_HEADERS
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["result"]["tools"], list)


@pytest.mark.anyio
async def test_unknown_method_is_method_not_found(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp", json=_rpc("resources/list"), headers=BOOTSTRAP_MCP_HEADERS
    )
    assert resp.json()["error"]["code"] == -32601


@pytest.mark.anyio
async def test_batch_requests_are_rejected(client, standard_mcp_enabled):
    resp = await client.post("/mcp", json=[_rpc("ping")], headers=BOOTSTRAP_MCP_HEADERS)
    assert resp.status_code == 400
    assert "error" in resp.json()


@pytest.mark.anyio
async def test_missing_accept_header_is_not_acceptable(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp",
        json=_rpc("ping"),
        headers={**BOOTSTRAP_HEADERS, "Accept": "text/plain"},
    )
    assert resp.status_code == 406


@pytest.mark.anyio
async def test_get_and_delete_are_method_not_allowed(client, standard_mcp_enabled):
    resp = await client.get("/mcp", headers=BOOTSTRAP_MCP_HEADERS)
    assert resp.status_code == 405
    assert resp.headers["allow"] == "POST"
    resp = await client.request("DELETE", "/mcp", headers=BOOTSTRAP_MCP_HEADERS)
    assert resp.status_code == 405


@pytest.mark.anyio
async def test_cross_origin_browser_calls_are_rejected(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp",
        json=_rpc("ping"),
        headers={**BOOTSTRAP_MCP_HEADERS, "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("origin", ["https://test", "http://test:444"])
async def test_standard_mcp_rejects_same_host_different_origin(
    client, standard_mcp_enabled, origin
):
    resp = await client.post(
        "/mcp",
        json=_rpc("ping"),
        headers={**BOOTSTRAP_MCP_HEADERS, "Origin": origin},
    )

    assert resp.status_code == 403


@pytest.mark.anyio
async def test_standard_mcp_uses_public_url_not_proxy_observed_scheme(
    client, standard_mcp_enabled, monkeypatch
):
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")
    get_settings.cache_clear()
    try:
        insecure = await client.post(
            "/mcp",
            json=_rpc("ping"),
            headers={
                **BOOTSTRAP_MCP_HEADERS,
                "Host": "api.example.com",
                "Origin": "http://api.example.com",
            },
        )
        canonical = await client.post(
            "/mcp",
            json=_rpc("ping"),
            headers={
                **BOOTSTRAP_MCP_HEADERS,
                "Host": "api.example.com",
                "Origin": "https://api.example.com",
            },
        )
    finally:
        monkeypatch.setenv("PUBLIC_URL", "")
        get_settings.cache_clear()

    assert insecure.status_code == 403
    assert canonical.status_code == 200


@pytest.mark.anyio
async def test_tools_call_requires_wallet_scoped_key(client, standard_mcp_enabled):
    resp = await client.post(
        "/mcp",
        json=_rpc("tools/call", params={"name": "anything", "arguments": {}}),
        headers=BOOTSTRAP_MCP_HEADERS,
    )
    error = resp.json()["error"]
    assert error["code"] == -32003
    assert "wallet_scoped_key_required" in error["message"]


@pytest.mark.anyio
async def test_tools_call_unknown_tool(client, standard_mcp_enabled, clean_database):
    provisioned = await provision_agent_wallet(client)
    resp = await client.post(
        "/mcp",
        json=_rpc("tools/call", params={"name": "no-such-tool", "arguments": {}}),
        headers={**provisioned["agent_headers"], **MCP_HEADERS},
    )
    assert resp.json()["error"]["code"] == -32001


@pytest.mark.anyio
async def test_tools_call_auto_mints_bounded_permit_and_charges_once(
    client, standard_mcp_enabled, clean_database
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    registry = get_service_registry()
    registry.register_local(
        service_id="standard-echo",
        name="Standard Echo",
        description="Standard MCP endpoint test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda message="ok": {"message": message},
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        call = _rpc(
            "tools/call",
            params={"name": "standard-echo", "arguments": {"message": "hi"}},
        )
        headers = {
            **provisioned["agent_headers"],
            **MCP_HEADERS,
            "Idempotency-Key": "standard-mcp-call-1",
        }
        resp = await client.post("/mcp", json=call, headers=headers)
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        receipt = result["receipt"]
        assert receipt["wallet_id"] == wallet_id
        # The receipt also rides the spec's extension point.
        assert result["_meta"]["io.agentmiddleware/receipt"] == receipt
        permit_id = receipt["permit_id"]

        # The auto-minted permit is a real signed permit, bounded to this
        # tool and the caller's own wallet/key.
        permit_resp = await client.get(
            f"/v1/permits/{permit_id}", headers=provisioned["agent_headers"]
        )
        assert permit_resp.status_code == 200
        permit = permit_resp.json()
        assert permit["issuer_wallet_id"] == wallet_id
        assert permit["subject_wallet_id"] == wallet_id
        assert permit["subject_key_id"] == provisioned["key_id"]
        assert permit["allowed_tools"] == ["standard-echo"]
        assert float(permit["max_credits"]) == 2.0

        # Replaying the same idempotency key returns the original receipt
        # without a second charge.
        replay = await client.post("/mcp", json=call, headers=headers)
        assert replay.status_code == 200
        assert replay.json()["result"]["receipt"]["receipt_id"] == receipt["receipt_id"]

        ledger = await client.get(
            f"/v1/billing/ledger/{wallet_id}", headers=provisioned["agent_headers"]
        )
        debits = [
            entry
            for entry in ledger.json()["entries"]
            if "standard-echo" in entry["description"]
        ]
        assert len(debits) == 1
    finally:
        registry.unregister_local("standard-echo")
