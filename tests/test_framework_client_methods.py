"""Untested framework_integrations surfaces: legacy client methods and factories.

tests/test_framework_legacy_client.py pins charge/discover/AWI-execute and
tests/test_framework_legacy_tools.py pins the LangGraph/LlamaIndex factories.
Nothing pinned the remaining B2AClient methods (balance, telemetry, message,
decide, heal, AWI session, MCP tools) or get_autogen_tools, which needs no
framework import at all: it returns the client's bound async methods. Every
test routes through httpx.MockTransport to prove a request actually left.
"""

from __future__ import annotations

import pytest

from framework_integrations import B2AClient, get_autogen_tools

WALLET_ID = "wallet-client-methods"
API_KEY = "client-methods-key"


@pytest.fixture
async def recording():
    sent: list = []
    bodies: dict[str, dict] = {}

    def handler(request):
        from httpx import Response

        sent.append(request)
        path = request.url.path
        if path == f"/v1/billing/wallets/{WALLET_ID}":
            return Response(200, json={"balance": 42.5})
        if path == "/v1/telemetry/events":
            return Response(200, json={"event_id": "evt-1"})
        if path == "/v1/comms/messages":
            return Response(200, json={"message_id": "msg-1"})
        if path == "/v1/ai/decide":
            return Response(200, json=bodies.get(path, {"decision": "b"}))
        if path == "/v1/ai/heal":
            return Response(200, json={"action": "restart"})
        if path == "/v1/awi/sessions":
            return Response(200, json={"session_id": "awi-123"})
        if path == "/mcp/tools.json":
            return Response(
                200,
                json=bodies.get(path, {"tools": [{"name": "t", "description": "d"}]}),
            )
        return Response(404, json={"detail": "unexpected request"})

    import httpx

    client = B2AClient(api_url="http://b2a.test", api_key=API_KEY, wallet_id=WALLET_ID)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield client, sent, bodies
    await client.close()


def _last(sent) -> object:
    assert len(sent) == 1
    request = sent[0]
    assert request.headers["X-API-Key"] == API_KEY
    return request


@pytest.mark.anyio
async def test_get_balance_returns_float_from_wallet_path(recording):
    client, sent, _ = recording
    assert await client.get_balance() == 42.5
    request = _last(sent)
    assert (request.method, request.url.path) == (
        "GET",
        f"/v1/billing/wallets/{WALLET_ID}",
    )


@pytest.mark.anyio
async def test_emit_telemetry_defaults_properties_to_empty_object(recording):
    import json

    client, sent, _ = recording
    assert await client.emit_telemetry("task_completed") == {"event_id": "evt-1"}
    request = _last(sent)
    assert (request.method, request.url.path) == ("POST", "/v1/telemetry/events")
    assert json.loads(request.content) == {
        "event": "task_completed",
        "agent_id": WALLET_ID,
        "properties": {},
    }


@pytest.mark.anyio
async def test_send_message_payload_names_sender_and_priority(recording):
    import json

    client, sent, _ = recording
    result = await client.send_message("agent-2", {"hello": "world"}, priority="high")
    assert result == {"message_id": "msg-1"}
    request = _last(sent)
    assert (request.method, request.url.path) == ("POST", "/v1/comms/messages")
    assert json.loads(request.content) == {
        "from_agent_id": WALLET_ID,
        "to_agent_id": "agent-2",
        "content": {"hello": "world"},
        "priority": "high",
    }


@pytest.mark.anyio
async def test_decide_returns_server_decision(recording):
    import json

    client, sent, _ = recording
    assert await client.decide({"goal": "ship"}, ["a", "b"]) == "b"
    request = _last(sent)
    assert (request.method, request.url.path) == ("POST", "/v1/ai/decide")
    assert json.loads(request.content) == {
        "agent_id": WALLET_ID,
        "context": {"goal": "ship"},
        "options": ["a", "b"],
    }


@pytest.mark.anyio
async def test_decide_falls_back_to_first_option_when_server_is_silent(recording):
    client, sent, bodies = recording
    bodies["/v1/ai/decide"] = {}
    assert await client.decide({"goal": "ship"}, ["a", "b"]) == "a"
    assert len(sent) == 1


@pytest.mark.anyio
async def test_decide_with_no_options_is_refused_before_transport(recording):
    client, sent, _ = recording
    with pytest.raises(ValueError, match="options"):
        await client.decide({"goal": "ship"}, [])
    assert sent == []


@pytest.mark.anyio
async def test_heal_posts_issue_and_context(recording):
    import json

    client, sent, _ = recording
    assert await client.heal("timeout", {"code": 504}) == {"action": "restart"}
    request = _last(sent)
    assert (request.method, request.url.path) == ("POST", "/v1/ai/heal")
    assert json.loads(request.content) == {"issue": "timeout", "context": {"code": 504}}


@pytest.mark.anyio
async def test_create_awi_session_posts_target_and_steps(recording):
    import json

    client, sent, _ = recording
    result = await client.create_awi_session("https://example.com", max_steps=5)
    assert result == {"session_id": "awi-123"}
    request = _last(sent)
    assert (request.method, request.url.path) == ("POST", "/v1/awi/sessions")
    assert json.loads(request.content) == {
        "target_url": "https://example.com",
        "max_steps": 5,
    }


@pytest.mark.anyio
async def test_get_mcp_tools_returns_tool_list(recording):
    client, sent, _ = recording
    assert await client.get_mcp_tools() == [{"name": "t", "description": "d"}]
    request = _last(sent)
    assert (request.method, request.url.path) == ("GET", "/mcp/tools.json")


@pytest.mark.anyio
async def test_get_mcp_tools_defaults_to_empty_list(recording):
    client, sent, bodies = recording
    bodies["/mcp/tools.json"] = {}
    assert await client.get_mcp_tools() == []
    assert len(sent) == 1


@pytest.mark.anyio
async def test_get_autogen_tools_await_the_client_and_send_requests(recording):
    """get_autogen_tools needs no framework: the values are awaitable methods."""
    client, sent, _ = recording
    tools = get_autogen_tools(client)
    assert isinstance(tools, dict)
    assert set(tools) == {
        "emit_telemetry",
        "get_balance",
        "send_message",
        "ai_decide",
        "self_heal",
        "create_awi_session",
    }

    assert await tools["get_balance"]() == 42.5
    assert await tools["ai_decide"]({"goal": "ship"}, ["a"]) == "b"
    assert await tools["create_awi_session"]("https://example.com") == {
        "session_id": "awi-123"
    }
    paths = [r.url.path for r in sent]
    assert paths == [
        f"/v1/billing/wallets/{WALLET_ID}",
        "/v1/ai/decide",
        "/v1/awi/sessions",
    ]
    assert all(r.headers["X-API-Key"] == API_KEY for r in sent)
