"""
Tests for signed capability permits: the PermitService, the tool-call
authorization helper, the HTTP endpoints, and MCP enforcement.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

import app.services.permits as permits_mod
from app.main import app
from app.routers import mcp as mcp_module
from app.services.permits import (
    PermitError,
    PermitService,
    get_permit_service,
    require_permit_for_tool,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- PermitService ---


def test_issue_and_decode_round_trip():
    svc = PermitService()
    issued = svc.issue(wallet_id="w1", scope=["tool-a"], max_spend=10)
    claims = svc.decode(issued["permit"])
    assert claims["wallet_id"] == "w1"
    assert claims["scope"] == ["tool-a"]
    assert claims["max_spend"] == "10"


def test_decode_rejects_tampered_token():
    svc = PermitService()
    token = svc.issue(wallet_id="w1", scope=["*"])["permit"]
    payload_b64, sig_b64 = token.split(".", 1)
    # Swap the signature for another permit's signature.
    other_sig = svc.issue(wallet_id="w2", scope=["*"])["permit"].split(".", 1)[1]
    with pytest.raises(PermitError):
        svc.decode(f"{payload_b64}.{other_sig}")


def test_decode_rejects_expired(monkeypatch):
    svc = PermitService()
    token = svc.issue(wallet_id="w1", scope=["*"], ttl_seconds=10)["permit"]

    class _FarFuture:
        @staticmethod
        def time():
            return 9_999_999_999

    monkeypatch.setattr(permits_mod, "time", _FarFuture)
    with pytest.raises(PermitError) as exc:
        svc.decode(token)
    assert "expired" in str(exc.value)


# --- require_permit_for_tool ---


@pytest.mark.anyio
async def test_permit_authorizes_in_scope_tool():
    svc = get_permit_service()
    token = svc.issue(wallet_id="w1", scope=["tool-a"])["permit"]
    claims = await require_permit_for_tool(token, wallet_id="w1", tool_name="tool-a")
    assert claims["wallet_id"] == "w1"


@pytest.mark.anyio
async def test_permit_rejects_out_of_scope_tool():
    svc = get_permit_service()
    token = svc.issue(wallet_id="w1", scope=["tool-a"])["permit"]
    with pytest.raises(PermitError) as exc:
        await require_permit_for_tool(token, wallet_id="w1", tool_name="tool-b")
    assert "out_of_scope" in str(exc.value)


@pytest.mark.anyio
async def test_permit_rejects_wallet_mismatch():
    svc = get_permit_service()
    token = svc.issue(wallet_id="w1", scope=["*"])["permit"]
    with pytest.raises(PermitError) as exc:
        await require_permit_for_tool(token, wallet_id="other", tool_name="x")
    assert "wallet_mismatch" in str(exc.value)


@pytest.mark.anyio
async def test_missing_permit_raises():
    with pytest.raises(PermitError) as exc:
        await require_permit_for_tool(None, wallet_id="w1", tool_name="x")
    assert "permit_required" in str(exc.value)


@pytest.mark.anyio
async def test_single_use_permit_cannot_be_replayed():
    svc = get_permit_service()
    token = svc.issue(wallet_id="w1", scope=["*"], single_use=True)["permit"]
    await require_permit_for_tool(token, wallet_id="w1", tool_name="x")
    with pytest.raises(PermitError) as exc:
        await require_permit_for_tool(token, wallet_id="w1", tool_name="x")
    assert "permit_replayed" in str(exc.value)


# --- spend allowance (max_spend) ---


@pytest.mark.anyio
async def test_consume_budget_accumulates_and_caps():
    from app.core.durable_state import get_durable_state

    store = get_durable_state()
    key = f"budget-{uuid.uuid4()}"

    ok, total = await store.consume_budget(key, 4.0, 10.0, 60)
    assert ok is True and total == 4.0
    ok, total = await store.consume_budget(key, 4.0, 10.0, 60)
    assert ok is True and total == 8.0
    # 8 + 4 = 12 > 10 -> rejected, total unchanged
    ok, total = await store.consume_budget(key, 4.0, 10.0, 60)
    assert ok is False and total == 8.0


@pytest.mark.anyio
async def test_permit_enforces_cumulative_spend_cap():
    svc = get_permit_service()
    token = svc.issue(wallet_id="w1", scope=["t"], max_spend=10)["permit"]

    await require_permit_for_tool(token, wallet_id="w1", tool_name="t", cost=4)
    await require_permit_for_tool(token, wallet_id="w1", tool_name="t", cost=4)
    with pytest.raises(PermitError) as exc:
        await require_permit_for_tool(token, wallet_id="w1", tool_name="t", cost=4)
    assert "spend_cap_exceeded" in str(exc.value)


@pytest.mark.anyio
async def test_permit_without_max_spend_ignores_cost():
    svc = get_permit_service()
    token = svc.issue(wallet_id="w1", scope=["t"])["permit"]  # no max_spend
    # Large cost is fine when no cap is set.
    claims = await require_permit_for_tool(
        token, wallet_id="w1", tool_name="t", cost=1000
    )
    assert claims["max_spend"] is None


# --- HTTP endpoints ---


@pytest.mark.anyio
async def test_issue_and_introspect_endpoints(client):
    headers = {"X-API-Key": "test-key"}
    issued = await client.post(
        "/v1/permits/issue",
        json={"wallet_id": "w-http", "scope": ["tool-a"], "ttl_seconds": 600},
        headers=headers,
    )
    assert issued.status_code == 200
    token = issued.json()["permit"]

    introspect = await client.post(
        "/v1/permits/introspect", json={"permit": token}, headers=headers
    )
    assert introspect.status_code == 200
    body = introspect.json()
    assert body["valid"] is True
    assert body["claims"]["wallet_id"] == "w-http"


@pytest.mark.anyio
async def test_introspect_rejects_garbage(client):
    headers = {"X-API-Key": "test-key"}
    resp = await client.post(
        "/v1/permits/introspect", json={"permit": "not-a-real-token"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


@pytest.mark.anyio
async def test_cross_wallet_permit_issue_denied(client):
    """A DB key scoped to wallet A cannot mint a permit for wallet B."""
    headers = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": f"p-{uuid.uuid4().hex[:6]}", "email": "p@test.example"},
        headers=headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "scoped"},
        headers=headers,
    )
    scoped = {"X-API-Key": key_resp.json()["api_key"]}

    denied = await client.post(
        "/v1/permits/issue",
        json={"wallet_id": "some-other-wallet", "scope": ["*"]},
        headers=scoped,
    )
    assert denied.status_code == 403


# --- MCP enforcement ---


@pytest.mark.anyio
async def test_mcp_tool_call_denied_without_permit_when_enforced(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "_permit_enforcement_enabled", lambda: True)
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "any-tool", "mcpContext": {"wallet_id": "w1"}},
        },
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "permit_denied"


@pytest.mark.anyio
async def test_mcp_tool_call_allowed_with_valid_permit(client, monkeypatch):
    monkeypatch.setattr(mcp_module, "_permit_enforcement_enabled", lambda: True)
    token = get_permit_service().issue(wallet_id="w1", scope=["any-tool"])["permit"]
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "any-tool", "mcpContext": {"wallet_id": "w1"}},
        },
        headers={"X-API-Key": "test-key", "X-Agent-Permit": token},
    )
    # Permit passed the gate; the tool itself doesn't exist, so we get a
    # JSON-RPC error rather than a 403 permit denial.
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "not found" in body["error"]["message"].lower()


@pytest.mark.anyio
async def test_http_invoke_path_also_enforces_permit(client, monkeypatch):
    """The HTTP invoke endpoint must enforce permits too — not just JSON-RPC —
    so PERMITS_ENFORCED cannot be bypassed by choosing the other path."""
    from app.schemas.billing import ServiceCategory
    from app.services.service_registry import get_service_registry

    monkeypatch.setattr(mcp_module, "_permit_enforcement_enabled", lambda: True)
    get_service_registry().register_local(
        service_id="echo-tool",
        name="Echo",
        description="echo",
        category=ServiceCategory.PLATFORM_FEE,
        func=lambda **kw: {"ok": True},
        credits_per_unit=1.0,
    )
    body = {"name": "echo-tool", "arguments": {}, "mcp_context": {"wallet_id": "w1"}}

    denied = await client.post(
        "/mcp/tools/echo-tool/invoke", json=body, headers={"X-API-Key": "test-key"}
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["error"] == "permit_denied"

    token = get_permit_service().issue(wallet_id="w1", scope=["echo-tool"])["permit"]
    allowed = await client.post(
        "/mcp/tools/echo-tool/invoke",
        json=body,
        headers={"X-API-Key": "test-key", "X-Agent-Permit": token},
    )
    assert allowed.status_code == 200
    assert allowed.json()["isError"] is False
