"""QA pass for ``app/routers/mcp.py``: tool invocation and approvals.

Pins router-level behavior that nearby suites do not cover: the JSON-RPC
envelope edges on ``POST /mcp/messages``, the REST error mapping on
``POST /mcp/tools/{service_id}/invoke`` (404, 402, 403, 202), the
single-tool catalog read, and tenant isolation on the REST path. Every
refusal asserts zero tool executions and zero ledger debits, so "refused"
means refused before any effect.

Product edits to ``app/routers/mcp.py`` are owned by in-flight work, so a
suspected router bug below is recorded as a strict xfail instead of a fix.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import app.services.human_approval as human_approval_module
from app.core.config import get_settings
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.human_approval import HumanApprovalService
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _register_tool(service_id: str, calls: list, credits_per_unit: float = 2.0):
    def _run(text: str = "ok") -> dict[str, Any]:
        calls.append(text)
        return {"text": text}

    registry = get_service_registry()
    registry.register_local(
        service_id=service_id,
        name=f"QA {service_id}",
        description="Router QA probe tool",
        category=ServiceCategory.AGENT_COMMS,
        func=_run,
        credits_per_unit=credits_per_unit,
        unit_name="call",
    )
    return registry


async def _debits(client: AsyncClient, wallet_id: str, headers: dict) -> int:
    ledger = await client.get(f"/v1/billing/ledger/{wallet_id}", headers=headers)
    assert ledger.status_code == 200, ledger.text
    return sum(1 for e in ledger.json()["entries"] if e["action"] == "debit")


# --------------------------------------------------------------------------- #
# POST /mcp/messages: envelope edges
# --------------------------------------------------------------------------- #


async def test_messages_unknown_method_returns_32601_and_echoes_id(
    client, clean_database
):
    resp = await client.post(
        "/mcp/messages",
        json={"jsonrpc": "2.0", "id": "u1", "method": "tools/bogus", "params": {}},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["id"] == "u1"
    assert payload["error"]["code"] == -32601
    assert "tools/bogus" in payload["error"]["message"]


async def test_messages_tools_list_returns_registered_tool(client, clean_database):
    calls: list = []
    registry = _register_tool("qa-list-echo", calls)
    try:
        resp = await client.post(
            "/mcp/messages",
            json={"jsonrpc": "2.0", "id": "l1", "method": "tools/list", "params": {}},
            headers=BOOTSTRAP_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert "qa-list-echo" in names
        assert calls == []
    finally:
        registry.unregister_local("qa-list-echo")


async def test_messages_tools_list_ignores_unknown_category_string(
    client, clean_database
):
    calls: list = []
    registry = _register_tool("qa-category-echo", calls)
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "l2",
                "method": "tools/list",
                "params": {"category": "not-a-category"},
            },
            headers=BOOTSTRAP_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert "qa-category-echo" in names
    finally:
        registry.unregister_local("qa-category-echo")


async def test_messages_tools_call_without_api_key_returns_401(client, clean_database):
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": "c0",
            "method": "tools/call",
            "params": {
                "name": "qa-list-echo",
                "arguments": {},
                "mcpContext": {"wallet_id": "w"},
            },
        },
    )
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# POST /mcp/tools/{service_id}/invoke: error mapping and isolation
# --------------------------------------------------------------------------- #


async def test_rest_invoke_unknown_tool_returns_404_without_charge(
    client, clean_database
):
    agent = await provision_agent_wallet(client)
    resp = await client.post(
        "/mcp/tools/qa-no-such-tool/invoke",
        json={
            "name": "qa-no-such-tool",
            "arguments": {},
            "mcp_context": {"wallet_id": agent["agent_wallet_id"]},
        },
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 404, resp.text
    assert "Tool not found" in resp.json()["detail"]
    assert await _debits(client, agent["agent_wallet_id"], agent["agent_headers"]) == 0


async def test_rest_invoke_cross_wallet_is_forbidden_without_effects(
    client, clean_database
):
    calls: list = []
    registry = _register_tool("qa-cross-rest-echo", calls)
    try:
        owner = await provision_agent_wallet(client)
        other = await provision_agent_wallet(client)
        resp = await client.post(
            "/mcp/tools/qa-cross-rest-echo/invoke",
            json={
                "name": "qa-cross-rest-echo",
                "arguments": {"text": "hello"},
                "mcp_context": {"wallet_id": other["agent_wallet_id"]},
            },
            headers=owner["agent_headers"],
        )
        assert resp.status_code == 403, resp.text
        assert "wallet_access_denied" in resp.json()["detail"]["error"]
        assert calls == []
        assert await _debits(client, other["agent_wallet_id"], BOOTSTRAP_HEADERS) == 0
        assert (
            await _debits(client, owner["agent_wallet_id"], owner["agent_headers"]) == 0
        )
    finally:
        registry.unregister_local("qa-cross-rest-echo")


async def test_rest_invoke_insufficient_funds_returns_402_without_running(
    client, clean_database
):
    calls: list = []
    registry = _register_tool("qa-expensive-echo", calls, credits_per_unit=5000.0)
    try:
        agent = await provision_agent_wallet(client)
        resp = await client.post(
            "/mcp/tools/qa-expensive-echo/invoke",
            json={
                "name": "qa-expensive-echo",
                "arguments": {},
                "mcp_context": {"wallet_id": agent["agent_wallet_id"]},
            },
            headers=agent["agent_headers"],
        )
        assert resp.status_code == 402, resp.text
        assert resp.json()["detail"] == "insufficient_funds"
        assert calls == []
        assert (
            await _debits(client, agent["agent_wallet_id"], agent["agent_headers"]) == 0
        )
    finally:
        registry.unregister_local("qa-expensive-echo")


# --------------------------------------------------------------------------- #
# Approvals over the REST surface
# --------------------------------------------------------------------------- #


class _PendingSentinel:
    """Sentinel stand-in that never decides, so the gate stays pending."""

    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_approval(self, **kwargs):
        self.created.append(kwargs)
        return {"action_id": "act_qa_pending", "status": "pending"}

    async def get_approval(self, action_id: str):
        return {"action_id": action_id, "status": "pending"}

    async def wait_approval(self, action_id: str, timeout: float):
        return await self.get_approval(action_id)


async def test_rest_invoke_pending_approval_returns_202_and_frees_key(
    client, clean_database, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "SIMULATION_MODE_HUMAN_APPROVAL", False)
    monkeypatch.setattr(settings, "SENTINEL_API_URL", "https://sentinel.test")
    monkeypatch.setattr(settings, "SENTINEL_API_KEY", "sk_test_" + "0" * 64)
    monkeypatch.setattr(settings, "SENTINEL_WAIT_SECONDS", 0.0)
    service = HumanApprovalService()
    monkeypatch.setattr(human_approval_module, "_service", service)
    fake = _PendingSentinel()
    monkeypatch.setattr(service, "_sentinel", lambda: fake)

    calls: list = []
    registry = _register_tool("qa-approval-rest-echo", calls)
    try:
        agent = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=agent["agent_wallet_id"],
            key_id=agent["key_id"],
            tool_name="qa-approval-rest-echo",
            max_credits=50,
            idem_key="qa-approval-permit-1",
            requires_human_approval=True,
        )
        body = {
            "name": "qa-approval-rest-echo",
            "arguments": {"text": "hello"},
            "mcp_context": {
                "wallet_id": agent["agent_wallet_id"],
                "permit_id": permit["permit_id"],
                "idempotency_key": "qa-approval-invoke-1",
            },
        }
        first = await client.post(
            "/mcp/tools/qa-approval-rest-echo/invoke",
            json=body,
            headers=agent["agent_headers"],
        )
        assert first.status_code == 202, first.text
        detail = first.json()["detail"]
        assert detail["error"] == "human_approval_pending"
        assert detail["approval"]["approval_status"] == "pending"
        assert calls == []
        assert (
            await _debits(client, agent["agent_wallet_id"], agent["agent_headers"]) == 0
        )

        # The key was freed, so the same invoke retries instead of conflicting.
        second = await client.post(
            "/mcp/tools/qa-approval-rest-echo/invoke",
            json=body,
            headers=agent["agent_headers"],
        )
        assert second.status_code == 202, second.text
        assert calls == []
    finally:
        registry.unregister_local("qa-approval-rest-echo")


# --------------------------------------------------------------------------- #
# Catalog reads
# --------------------------------------------------------------------------- #


async def test_get_single_tool_returns_definition(client, clean_database):
    calls: list = []
    registry = _register_tool("qa-single-echo", calls)
    try:
        resp = await client.get("/mcp/tools/qa-single-echo")
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "qa-single-echo"
    finally:
        registry.unregister_local("qa-single-echo")


# --------------------------------------------------------------------------- #
# Suspected router bug (not fixed: file owned by in-flight work)
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason="BUG-qa-mcp-bool-id: _safe_jsonrpc_id nulls a boolean id and the "
    "router dispatches the paid tools/call instead of refusing the invalid "
    "envelope before effects (app/routers/mcp.py).",
)
async def test_messages_boolean_id_is_refused_before_effects(client, clean_database):
    calls: list = []
    registry = _register_tool("qa-bool-id-echo", calls)
    try:
        agent = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=agent["agent_wallet_id"],
            key_id=agent["key_id"],
            tool_name="qa-bool-id-echo",
            max_credits=50,
            idem_key="qa-bool-id-permit-1",
        )
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": True,
                "method": "tools/call",
                "params": {
                    "name": "qa-bool-id-echo",
                    "arguments": {"text": "hello"},
                    "mcpContext": {
                        "wallet_id": agent["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "qa-bool-id-invoke-1",
                    },
                },
            },
            headers=agent["agent_headers"],
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["id"] is None
        assert payload["error"]["code"] == -32600
        assert calls == []
        assert (
            await _debits(client, agent["agent_wallet_id"], agent["agent_headers"]) == 0
        )
    finally:
        registry.unregister_local("qa-bool-id-echo")
