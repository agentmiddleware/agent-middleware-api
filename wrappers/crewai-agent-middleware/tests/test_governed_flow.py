"""Tests for governed permit→invoke→receipt flow in CrewAI wrapper."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from crewai_b2a import B2AClient, CrewAIB2ATool


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
    # Mirrors the receipt shape b2a_sdk.models.Receipt.from_dict requires
    # (see b2a_sdk/tests/test_trust_client.py).
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
async def test_call_tool_requires_idempotency_key():
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
    tool = CrewAIB2ATool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    result = await tool._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="invoke-key-1",
        permit_idempotency_key="permit-invoke-key-1",
        arguments={"query": "test"},
    )

    assert permit_called
    assert invoke_called
    assert "receipt-success" in result

    result_blank = await tool._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="   ",
        permit_idempotency_key="permit-key",
        arguments={},
    )
    assert "Error: idempotency_key is required" in result_blank

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
    tool = CrewAIB2ATool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    result1 = await tool._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="replay-key",
        permit_idempotency_key="permit-replay-key",
        arguments={"query": "first"},
    )

    result2 = await tool._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="replay-key",
        permit_idempotency_key="permit-replay-key",
        arguments={"query": "second"},
    )

    assert "receipt-success" in result1
    assert "receipt-success" in result2

    await base_client.close()


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
    base_client = B2AClient(api_key="test-key", transport=transport)
    tool = CrewAIB2ATool(api_key="test-key", wallet_id="wallet-1")
    tool.client = base_client

    result = await tool._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="signed-key",
        permit_idempotency_key="permit-signed-key",
        arguments={},
    )

    assert "receipt_id" in result
    assert "signature" in result
    assert "credits_charged" in result
    assert "sig-success" in result
    assert "'2'" in result

    await base_client.close()
