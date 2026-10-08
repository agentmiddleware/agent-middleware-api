"""Sync bridge, typed errors, schema wiring, and base_url defaults.

Regression tests for the go-to-market review slice gtm-33: the CrewAI sync
entry point must work with and without a running event loop, failures must
raise instead of returning "Error: ..." strings, the input schema must be
wired as args_schema, and the default base_url must not point at a test host.
"""

import ast
import json
from datetime import datetime, timezone

import httpx
import pytest
from b2a_sdk import IdempotencyConflictError

from crewai_b2a import B2AClient, CrewAIB2ATool
from crewai_b2a.tool import CrewAIOperationSchema, LOCAL_GATEWAY_URL


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


def _make_tool(**overrides) -> tuple[CrewAIB2ATool, B2AClient]:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            return httpx.Response(201, json=_permit_payload())
        if request.url.path == "/mcp/messages":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [{"type": "text", "text": '{"ok": true}'}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )
        return httpx.Response(404)

    base_client = B2AClient(api_key="test-key", transport=httpx.MockTransport(handler))
    kwargs = {"api_key": "test-key", "wallet_id": "wallet-1"}
    kwargs.update(overrides)
    tool = CrewAIB2ATool(**kwargs)
    tool.client = base_client
    return tool, base_client


def _call_kwargs(**overrides) -> dict:
    call = {
        "operation": "call_tool",
        "tool_name": "partner.search",
        "idempotency_key": "sync-key-1",
        "permit_idempotency_key": "sync-permit-key-1",
        "arguments": {"query": "test"},
    }
    call.update(overrides)
    return call


def test_sync_run_without_running_loop_returns_receipt():
    """The sync entry point works from plain synchronous code (no event loop)."""
    tool, base_client = _make_tool()
    try:
        result = tool._run(**_call_kwargs())
    finally:
        httpx_close(base_client)
    assert ast.literal_eval(result)["receipt_id"] == "receipt-success"


def httpx_close(client: B2AClient) -> None:
    """Close an async client from sync test code via the same loop-safe bridge."""
    from crewai_b2a.tool import _await_sync

    _await_sync(client.close())


@pytest.mark.asyncio
async def test_sync_run_inside_running_loop_returns_receipt():
    """The sync entry point also works when a loop is already running.

    The old bridge (asyncio.get_event_loop().run_until_complete) raises
    RuntimeError on a running loop, which the old code then swallowed into an
    "Error: ..." string. This test fails on that code and passes on the
    thread-bridged runner.
    """
    tool, base_client = _make_tool()
    try:
        result = tool._run(**_call_kwargs())
    finally:
        await base_client.close()
    assert ast.literal_eval(result)["receipt_id"] == "receipt-success"


@pytest.mark.asyncio
async def test_unknown_operation_raises_value_error():
    tool, base_client = _make_tool()
    try:
        with pytest.raises(ValueError, match="Unknown operation"):
            await tool._arun(operation="launch_rockets")
    finally:
        await base_client.close()


def test_unknown_operation_raises_on_sync_path():
    tool, base_client = _make_tool()
    try:
        with pytest.raises(ValueError, match="Unknown operation"):
            tool._run(operation="launch_rockets")
    finally:
        httpx_close(base_client)


@pytest.mark.asyncio
async def test_missing_tool_name_raises_value_error():
    tool, base_client = _make_tool()
    try:
        with pytest.raises(ValueError, match="tool_name is required"):
            await tool._arun(
                operation="call_tool",
                tool_name="  ",
                idempotency_key="k",
                permit_idempotency_key="pk",
                arguments={},
            )
    finally:
        await base_client.close()


@pytest.mark.asyncio
async def test_blank_permit_key_raises_value_error():
    tool, base_client = _make_tool()
    try:
        with pytest.raises(ValueError, match="permit_idempotency_key"):
            await tool._arun(
                operation="call_tool",
                tool_name="partner.search",
                idempotency_key="k",
                permit_idempotency_key="   ",
                arguments={},
            )
    finally:
        await base_client.close()


def test_idempotency_conflict_type_is_importable():
    """Billing conflicts surface as the typed SDK error, not a string."""
    assert issubclass(IdempotencyConflictError, Exception)


def test_args_schema_is_wired():
    """The operation schema is wired so CrewAI tool-calling parses arguments."""
    tool, _ = _make_tool()
    assert tool.args_schema is CrewAIOperationSchema
    fields = CrewAIOperationSchema.model_fields
    assert set(fields) >= {
        "operation",
        "tool_name",
        "idempotency_key",
        "permit_idempotency_key",
        "arguments",
    }
    assert fields["operation"].is_required()


def test_default_base_url_is_local_not_test_host():
    """A forgotten base_url override fails loudly on localhost, never bills a test host."""
    tool, _ = _make_tool()
    assert tool.base_url == LOCAL_GATEWAY_URL
    assert "thisisatest" not in tool.base_url


def test_explicit_base_url_is_honored():
    tool, _ = _make_tool(base_url="https://gateway.example.com")
    assert tool.base_url == "https://gateway.example.com"
