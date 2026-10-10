"""Known replay conflicts must be distinct from unclassified server failures."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL = "conflict-surface-echo"
OTHER_TOOL = "conflict-surface-other"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def standard_mcp_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.setenv("ENABLE_STANDARD_MCP_ENDPOINT", "false")
    get_settings.cache_clear()


@pytest.fixture
def tool_calls():
    calls: list[str] = []

    def echo(message: str) -> dict[str, str]:
        calls.append(message)
        return {"message": message}

    registry = get_service_registry()
    for name in (TOOL, OTHER_TOOL):
        registry.register_local(
            service_id=name,
            name=name,
            description="Replay conflict regression fixture",
            category=ServiceCategory.AGENT_COMMS,
            func=echo,
            credits_per_unit=2,
            unit_name="call",
        )
    yield calls
    for name in (TOOL, OTHER_TOOL):
        registry.unregister_local(name)


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["/mcp/messages", "/mcp/tools/invoke", "/mcp"])
async def test_changed_body_conflicts_without_second_execution_or_debit(
    endpoint, clean_database, standard_mcp_enabled, tool_calls
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        owner = await provision_agent_wallet(client)
        wallet_id = owner["agent_wallet_id"]
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=owner["key_id"],
            tool_name=TOOL,
            idem_key="conflict-surface-permit",
        )
        headers = {
            **owner["agent_headers"],
            **MCP_HEADERS,
            "Idempotency-Key": "conflict-surface-call",
        }

        async def call(message, request_id):
            params = {"name": TOOL, "arguments": {"message": message}}
            context = {"wallet_id": wallet_id, "permit_id": permit["permit_id"]}
            if endpoint == "/mcp/tools/invoke":
                return await client.post(
                    f"/mcp/tools/{TOOL}/invoke",
                    json={**params, "mcp_context": context},
                    headers=headers,
                )
            if endpoint == "/mcp/messages":
                params["mcpContext"] = context
            return await client.post(
                endpoint,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": request_id,
                    "params": params,
                },
                headers=headers,
            )

        first = await call("first", "first-id")
        replay = await call("first", "replay-id")
        assert first.status_code == replay.status_code == 200
        if endpoint == "/mcp/tools/invoke":
            result = first.json()
            assert replay.json() == result
        else:
            result = first.json()["result"]
            assert replay.json()["result"] == result
            assert replay.json()["id"] == "replay-id"
        assert Decimal(result["receipt"]["credits_charged"]) == Decimal("2")

        conflict = await call("changed", "conflict-id")
        if endpoint == "/mcp/tools/invoke":
            assert conflict.status_code == 409, conflict.text
            assert conflict.json() == {"detail": "idempotency_key_reused"}
        else:
            assert conflict.status_code == 200
            assert conflict.json()["id"] == "conflict-id"
            assert conflict.json()["error"] == {
                "code": -32009,
                "message": "idempotency_key_reused",
            }

        final_replay = await call("first", "final-replay-id")
        final_result = final_replay.json()
        if endpoint != "/mcp/tools/invoke":
            final_result = final_result["result"]
        assert final_result == result
        ledger = await client.get(
            f"/v1/billing/ledger/{wallet_id}", headers=owner["agent_headers"]
        )
        assert ledger.status_code == 200, ledger.text
        debits = [row for row in ledger.json()["entries"] if row["action"] == "debit"]
        assert len(debits) == 1
        assert tool_calls == ["first"]


@pytest.mark.anyio
async def test_standard_auto_permit_conflict_has_same_application_code(
    clean_database, standard_mcp_enabled, tool_calls
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        owner = await provision_agent_wallet(client)
        headers = {
            **owner["agent_headers"],
            **MCP_HEADERS,
            "Idempotency-Key": "conflict-surface-auto-permit",
        }
        for tool in (TOOL, OTHER_TOOL):
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": tool,
                    "params": {"name": tool, "arguments": {"message": "first"}},
                },
                headers=headers,
            )
            assert response.status_code == 200
            if tool == TOOL:
                assert Decimal(
                    response.json()["result"]["receipt"]["credits_charged"]
                ) == Decimal("2")
            else:
                assert response.json()["error"] == {
                    "code": -32009,
                    "message": "idempotency_key_reused",
                }
        assert tool_calls == ["first"]
