"""Key validation, tool allowlist, and durable permit store for the AutoGen wrapper."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from autogen_b2a import B2AClient, B2AFunctionTool


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


def _receipt_payload() -> dict:
    return {
        "receipt_id": "receipt-success",
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
        "outcome": "success",
        "audit_event_id": "audit-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signature": "sig-success",
        "signature_key_id": "signing-key-1",
    }


def _wire(tool: B2AFunctionTool, handler) -> B2AClient:
    base_client = B2AClient(api_key="test-key", transport=httpx.MockTransport(handler))
    tool.client = base_client
    return base_client


def _governed_handler(request: httpx.Request) -> httpx.Response:
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


@pytest.mark.asyncio
async def test_overlong_idempotency_key_rejected_before_http():
    """A key longer than the trust plane column fails before any network call."""
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404)

    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    base_client = _wire(tool, handler)

    with pytest.raises(ValueError, match="too long"):
        await tool.call_mcp_tool(
            tool_name="partner.search",
            idempotency_key="k" * 129,
            permit_idempotency_key="permit-key",
            arguments={},
        )
    with pytest.raises(ValueError, match="too long"):
        await tool.call_mcp_tool(
            tool_name="partner.search",
            idempotency_key="invoke-key",
            permit_idempotency_key="p" * 129,
            arguments={},
        )
    assert calls == []

    await base_client.close()


@pytest.mark.asyncio
async def test_padded_or_non_ascii_key_rejected_before_http():
    """Surrounding whitespace and non-ASCII fail client-side, not at the server."""
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404)

    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    base_client = _wire(tool, handler)

    for bad in ("  padded-key", "padded-key  ", "clé-1", "key\nnewline"):
        with pytest.raises(ValueError, match="printable ASCII"):
            await tool.call_mcp_tool(
                tool_name="partner.search",
                idempotency_key=bad,
                permit_idempotency_key="permit-key",
                arguments={},
            )
    assert calls == []

    await base_client.close()


@pytest.mark.asyncio
async def test_unregistered_tool_refused_when_allowlist_set():
    """With allowed_tools, the model cannot name arbitrary tools."""
    tool = B2AFunctionTool(
        api_key="test-key",
        wallet_id="wallet-1",
        allowed_tools=["partner.search"],
    )
    base_client = _wire(tool, _governed_handler)

    with pytest.raises(ValueError, match="not registered"):
        await tool.call_mcp_tool(
            tool_name="partner.delete",
            idempotency_key="invoke-key",
            permit_idempotency_key="permit-key",
            arguments={},
        )

    result = await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="invoke-key",
        permit_idempotency_key="permit-key",
        arguments={},
    )
    assert result["receipt_id"] == "receipt-success"

    await base_client.close()


def test_register_tool_adds_to_allowlist_and_rejects_bad_names():
    tool = B2AFunctionTool(api_key="test-key", wallet_id="wallet-1")
    assert tool.register_tool("partner.search") == "partner.search"
    assert tool.register_tool("partner.search") == "partner.search"

    with pytest.raises(ValueError, match="not registered"):
        tool._require_tool_allowed("partner.delete")

    with pytest.raises(ValueError, match="non-blank"):
        tool.register_tool("   ")
    with pytest.raises(ValueError, match="too long"):
        tool.register_tool("t" * 129)


def test_allowed_tools_constructor_validates_names():
    with pytest.raises(ValueError, match="tool name"):
        B2AFunctionTool(
            api_key="test-key", wallet_id="wallet-1", allowed_tools=["ok-tool", ""]
        )


@pytest.mark.asyncio
async def test_key_store_resume_reuses_permit_and_permit_body(tmp_path):
    """A second process with the same key_store_path resends the identical permit body.

    The resumed instance must not mint a fresh expires_at under the same
    permit key: the recorded request snapshot is replayed byte for byte, and
    no second permit is created.
    """
    store = tmp_path / "autogen-keys.json"
    permit_bodies: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            permit_bodies.append(request.content.decode())
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

    first = B2AFunctionTool(
        api_key="test-key", wallet_id="wallet-1", key_store_path=store
    )
    base_client = _wire(first, handler)
    await first.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="invoke-key-1",
        permit_idempotency_key="permit-resume-key",
        arguments={"query": "same"},
    )
    await base_client.close()
    assert store.exists()

    # A fresh instance stands in for the resumed process: it starts with
    # empty memory and recovers the recorded permit from the store file.
    second = B2AFunctionTool(
        api_key="test-key", wallet_id="wallet-1", key_store_path=store
    )
    assert second._permit_cache == {"permit-resume-key": "permit-1"}
    assert list(second._permit_requests) == ["permit-resume-key"]
    second_client = _wire(second, handler)
    await second.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="invoke-key-2",
        permit_idempotency_key="permit-resume-key",
        arguments={"query": "same"},
    )
    await second_client.close()

    assert len(permit_bodies) == 1


@pytest.mark.asyncio
async def test_key_store_resume_without_permit_id_resends_recorded_body(tmp_path):
    """A crash between recording the request and receiving the permit id replays it.

    The store holds the request snapshot but no permit id, so the resumed
    instance must POST the recorded body unchanged, not a fresh timestamp.
    """
    store = tmp_path / "autogen-keys.json"
    recorded = {
        "issuer_wallet_id": "wallet-1",
        "subject_wallet_id": "wallet-1",
        "subject_key_id": None,
        "scopes": ["tool:partner.search:invoke", "billing:charge"],
        "allowed_tools": ["partner.search"],
        "max_credits": "100",
        "expires_at": "2030-01-01T00:00:00+00:00",
    }
    store.write_text(
        json.dumps(
            {"permits": {"permit-crash-key": {"permit_id": None, "request": recorded}}}
        ),
        encoding="utf-8",
    )
    posted: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            posted.append(json.loads(request.content))
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

    tool = B2AFunctionTool(
        api_key="test-key", wallet_id="wallet-1", key_store_path=store
    )
    base_client = _wire(tool, handler)
    await tool.call_mcp_tool(
        tool_name="partner.search",
        idempotency_key="invoke-key-1",
        permit_idempotency_key="permit-crash-key",
        arguments={"query": "same"},
    )
    await base_client.close()

    assert posted == [recorded]
