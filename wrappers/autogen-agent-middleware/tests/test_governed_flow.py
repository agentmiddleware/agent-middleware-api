"""Tests for governed permit→invoke→receipt flow in AutoGen wrapper."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from autogen.agentchat.conversable_agent import ConversableAgent

from autogen_b2a import B2AClient, B2AFunctionTool, register_b2a_tools


def _permit_payload() -> dict:
    return {
        "permit_id": "permit-1",
        "issuer_wallet_id": "wallet-1",
        "subject_wallet_id": "wallet-1",
        "subject_key_id": "key-1",
        "scopes": ["tool:partner.search:invoke", "billing:charge"],
        "allowed_tools": ["partner.search"],
        "max_credits": "100",
        "spent_credits": "0",
        "expires_at": datetime.now(timezone.utc).isoformat(),
        "nonce": "nonce-1",
        "status": "active",
        "signature": "sig-permit-1",
        "key_id": "key-1",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
    }


def _receipt_payload(outcome: str = "success") -> dict:
    # Mirrors the shape ``b2a_sdk.models.Receipt.from_dict`` requires (see
    # b2a_sdk/tests/test_trust_client.py): ``tool``, ``request_hash``,
    # ``credits_authorized``, ``created_at`` and ``signature_key_id`` are mandatory.
    return {
        "receipt_id": f"receipt-{outcome}",
        "permit_id": "permit-1",
        "wallet_id": "wallet-1",
        "key_id": "key-1",
        "tool": "partner.search",
        "request_hash": "request-hash",
        "response_hash": "response-hash",
        "ledger_entry_id": "ledger-1",
        "dispatch_attempt_id": "dispatch-1",
        "credits_authorized": "2",
        "credits_charged": "2",
        "outcome": outcome,
        "audit_event_id": "audit-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signature": f"sig-{outcome}",
        "signature_key_id": "signing-key-1",
    }


@pytest.mark.asyncio
async def test_call_mcp_tool_requires_idempotency_key():
    """Test that idempotency_key is required and must not be blank."""
    permit_called = False
    invoke_called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal permit_called, invoke_called

        if request.url.path == "/v1/permits":
            permit_called = True
            assert request.headers["idempotency-key"] == "permit-invoke-key-1"
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            invoke_called = True
            assert request.headers["idempotency-key"] == "invoke-key-1"
            body = json.loads(request.content)
            assert body["params"]["mcpContext"]["idempotency_key"] == "invoke-key-1"
            assert body["params"]["mcpContext"]["permit_id"] == "permit-1"
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "invoke-key-1",
                    "result": {
                        "content": [{"type": "text", "text": '{"ok": true}'}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    base_client = B2AClient(api_key="test-key", transport=transport)
    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    result = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="invoke-key-1",
        permit_idempotency_key="permit-invoke-key-1",
        arguments={"query": "test"},
    )

    assert permit_called
    assert invoke_called
    assert result["receipt_id"] == "receipt-success"
    assert result["signature"] == "sig-success"

    with pytest.raises(ValueError, match="must not be blank"):
        await tool.call_mcp_tool(
            tool_name="partner.search",
            idempotency_key="   ",
            permit_idempotency_key="permit-key",
            arguments={},
        )

    await base_client.close()


@pytest.mark.asyncio
async def test_replay_protection():
    """Test that replaying the same idempotency key is handled by the server."""
    call_count = {"permit": 0, "invoke": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            call_count["permit"] += 1
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            call_count["invoke"] += 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "replay-key",
                    "result": {
                        "content": [{"type": "text", "text": '{"replayed": true}'}],
                        "structuredContent": {"replayed": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    base_client = B2AClient(api_key="test-key", transport=transport)
    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    result1 = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="replay-key",
        permit_idempotency_key="permit-replay-key",
        arguments={"query": "first"},
    )

    result2 = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="replay-key",
        permit_idempotency_key="permit-replay-key",
        arguments={"query": "second"},
    )

    assert result1["receipt_id"] == "receipt-success"
    assert result2["receipt_id"] == "receipt-success"

    await base_client.close()


@pytest.mark.asyncio
async def test_signed_receipt_returned():
    """Test that signed receipts are returned with all required fields."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "signed-key",
                    "result": {
                        "content": [{"type": "text", "text": '{"status": "ok"}'}],
                        "structuredContent": {"status": "ok"},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    base_client = B2AClient(api_key="test-key", transport=transport)
    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    result = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="signed-key",
        permit_idempotency_key="permit-signed-key",
        arguments={},
    )

    assert "receipt_id" in result
    assert "signature" in result
    assert "credits_charged" in result
    assert result["signature"] == "sig-success"
    assert result["credits_charged"] == "2"
    assert result["structured_content"] == {"status": "ok"}

    await base_client.close()


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected():
    """Test that missing idempotency_key is rejected before any API call."""
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    base_client = B2AClient(api_key="test-key", transport=transport)
    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    with pytest.raises(ValueError, match="required"):
        await tool.call_mcp_tool(
            tool_name="partner.search",
            idempotency_key="",
            permit_idempotency_key="permit-key",
            arguments={},
        )

    await base_client.close()


@pytest.mark.asyncio
async def test_registered_tool_is_awaited_on_autogen_async_path():
    """register_b2a_tools hands AutoGen coroutine functions; a_execute_function must await them.

    AutoGen 0.2's sync execute_function calls func(**arguments) without awaiting, so a
    registered coroutine would surface as ``str(coroutine)``. The async executor path is
    the supported one; this pins that it awaits and returns the signed receipt.
    """
    calls = {"permit": 0, "invoke": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            calls["permit"] += 1
            assert request.headers["idempotency-key"] == "autogen-permit-1"
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            calls["invoke"] += 1
            body = json.loads(request.content)
            assert request.headers["idempotency-key"] == "autogen-invoke-1"
            assert body["params"]["mcpContext"]["idempotency_key"] == "autogen-invoke-1"
            assert body["params"]["arguments"] == {"query": "test"}
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "autogen-invoke-1",
                    "result": {
                        "content": [{"type": "text", "text": '{"ok": true}'}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    base_client = B2AClient(api_key="test-key", transport=transport)
    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    executor = ConversableAgent(
        name="executor",
        llm_config=False,
        human_input_mode="NEVER",
        code_execution_config=False,
    )
    register_b2a_tools(executor, tool)

    ok, message = await executor.a_execute_function(
        {
            "name": "call_mcp_tool",
            "arguments": json.dumps(
                {
                    "tool_name": "partner.search",
                    "idempotency_key": "autogen-invoke-1",
                    "permit_idempotency_key": "autogen-permit-1",
                    "arguments": {"query": "test"},
                }
            ),
        }
    )

    assert ok, message
    assert "coroutine" not in message["content"]
    assert "receipt-success" in message["content"]
    assert "sig-success" in message["content"]
    assert calls == {"permit": 1, "invoke": 1}

    await base_client.close()
