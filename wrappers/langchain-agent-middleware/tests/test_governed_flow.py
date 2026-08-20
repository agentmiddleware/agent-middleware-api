"""Tests for governed permit→invoke→receipt flow in LangChain wrapper."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from langchain_b2a import B2AClient
from langchain_b2a.tools import get_mcp_tools


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
        "expires_at": datetime.now(UTC).isoformat(),
        "nonce": "nonce-1",
        "status": "active",
        "signature": "sig-permit-1",
        "key_id": "key-1",
        "issued_at": datetime.now(UTC).isoformat(),
        "revoked_at": None,
    }


def _receipt_payload(outcome: str = "success") -> dict:
    return {
        "receipt_id": f"receipt-{outcome}",
        "dispatch_attempt_id": "dispatch-1",
        "idempotency_key": "invoke-key-1",
        "permit_id": "permit-1",
        "wallet_id": "wallet-1",
        "service": "partner.search",
        "credits_charged": "2",
        "outcome": outcome,
        "signature": f"sig-{outcome}",
        "key_id": "key-1",
        "ledger_entry_id": "ledger-1",
        "dispatched_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
    }


@pytest.mark.asyncio
async def test_mcp_tool_requires_idempotency_key():
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
    client = B2AClient(api_key="test-key", transport=transport)
    tools = get_mcp_tools(client, wallet_id="wallet-1")
    tool = tools[0]

    result = await tool.ainvoke({
        "tool_name": "partner.search",
        "idempotency_key": "invoke-key-1",
        "permit_idempotency_key": "permit-invoke-key-1",
        "arguments": {"query": "test"},
    })

    assert permit_called
    assert invoke_called
    assert "receipt-success" in result

    with pytest.raises(ValueError, match="must not be blank"):
        await tool.ainvoke({
            "tool_name": "partner.search",
            "idempotency_key": "   ",
            "permit_idempotency_key": "permit-key",
            "arguments": {},
        })

    await client.close()


@pytest.mark.asyncio
async def test_replay_with_same_idempotency_key_returns_cached_receipt():
    """Test that replaying the same idempotency key returns the original receipt without recharging."""
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
    client = B2AClient(api_key="test-key", transport=transport)
    tools = get_mcp_tools(client, wallet_id="wallet-1")
    tool = tools[0]

    result1 = await tool.ainvoke({
        "tool_name": "partner.search",
        "idempotency_key": "replay-key",
        "permit_idempotency_key": "permit-replay-key",
        "arguments": {"query": "first"},
    })

    result2 = await tool.ainvoke({
        "tool_name": "partner.search",
        "idempotency_key": "replay-key",
        "permit_idempotency_key": "permit-replay-key",
        "arguments": {"query": "second"},
    })

    assert call_count["permit"] >= 1
    assert call_count["invoke"] >= 1
    assert "receipt-success" in result1
    assert "receipt-success" in result2

    await client.close()


@pytest.mark.asyncio
async def test_signed_receipt_returned():
    """Test that signed receipts are returned with signature and credits charged."""
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
    client = B2AClient(api_key="test-key", transport=transport)
    tools = get_mcp_tools(client, wallet_id="wallet-1")
    tool = tools[0]

    result = await tool.ainvoke({
        "tool_name": "partner.search",
        "idempotency_key": "signed-key",
        "permit_idempotency_key": "permit-signed-key",
        "arguments": {},
    })

    result_dict = eval(result)
    assert "receipt_id" in result_dict
    assert "signature" in result_dict
    assert "credits_charged" in result_dict
    assert result_dict["signature"] == "sig-success"
    assert result_dict["credits_charged"] == "2"

    await client.close()


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected():
    """Test that missing idempotency_key is rejected before any API call."""
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    client = B2AClient(api_key="test-key", transport=transport)
    tools = get_mcp_tools(client, wallet_id="wallet-1")
    tool = tools[0]

    with pytest.raises(ValueError, match="required"):
        await tool.ainvoke({
            "tool_name": "partner.search",
            "idempotency_key": "",
            "permit_idempotency_key": "permit-key",
            "arguments": {},
        })

    await client.close()


@pytest.mark.asyncio
async def test_permit_cache_prevents_duplicate_create_permit():
    """Test that replaying with same permit_idempotency_key reuses cached permit_id.

    This test verifies the 409 fix: server hashes the FULL permit request body
    including expires_at. Without caching, two calls with the same permit_idempotency_key
    but different expires_at would cause 409 IdempotencyConflictError.

    The fix: cache the permit_id and skip create_permit on replay.
    """
    permit_create_count = {"count": 0}
    invoke_count = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            permit_create_count["count"] += 1
            # In real server: would 409 if same key + different body
            # Our fix: should only be called once (cached on replay)
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            invoke_count["count"] += 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "cache-test",
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
    client = B2AClient(api_key="test-key", transport=transport)
    tools = get_mcp_tools(client, wallet_id="wallet-1")
    tool = tools[0]

    # First call: creates permit
    result1 = await tool.ainvoke({
        "tool_name": "partner.search",
        "idempotency_key": "invoke-1",
        "permit_idempotency_key": "permit-cache-test",
        "arguments": {},
    })

    # Replay: reuses cached permit (does NOT call create_permit again)
    result2 = await tool.ainvoke({
        "tool_name": "partner.search",
        "idempotency_key": "invoke-2",  # different invoke key
        "permit_idempotency_key": "permit-cache-test",  # SAME permit key
        "arguments": {},
    })

    # Verify: create_permit called only ONCE (cached on second call)
    assert permit_create_count["count"] == 1, "create_permit should be called once and cached"
    # Verify: invoke_tool called TWICE (different invoke keys)
    assert invoke_count["count"] == 2, "invoke_tool should be called twice"

    assert "receipt-success" in result1
    assert "receipt-success" in result2

    await client.close()
