"""Permit-key reuse guard for the LangChain wrapper.

The tool caches the permit request body by permit_idempotency_key so a replay
reuses the original permit instead of triggering a server conflict. Reusing a
key whose cached terms differ from the current call must be rejected, the same
way the autogen and crewai wrappers reject it. Wallet and budget are fixed per
tool instance, so those comparisons are exercised by replacing the cached
request with one issued under different terms, then reusing the same key.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

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
        "created_at": datetime.now(UTC).isoformat(),
        "signature": "sig-success",
        "signature_key_id": "signing-key-1",
    }


def _transport() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            return httpx.Response(201, json=_permit_payload())
        if request.url.path == "/mcp/messages":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "x",
                    "result": {
                        "content": [{"type": "text", "text": '{"ok": true}'}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _permit_requests(tool):
    """Return the tool's cached permit-request dict from its closure."""
    fn = tool.coroutine
    assert fn is not None, "expected an async LangChain tool"
    names = fn.__code__.co_freevars
    cells = fn.__closure__ or ()
    return dict(zip(names, (c.cell_contents for c in cells)))["permit_requests"]


async def _first_call(tool, permit_key="permit-reuse-key"):
    return await tool.ainvoke(
        {
            "tool_name": "partner.search",
            "idempotency_key": "invoke-1",
            "permit_idempotency_key": permit_key,
            "arguments": {},
        }
    )


@pytest.mark.asyncio
async def test_reuse_with_different_tool_rejected():
    client = B2AClient(api_key="test-key", transport=_transport())
    tool = get_mcp_tools(client, wallet_id="wallet-1")[0]
    await _first_call(tool)

    with pytest.raises(ValueError, match="different permit terms"):
        await tool.ainvoke(
            {
                "tool_name": "partner.other",
                "idempotency_key": "invoke-2",
                "permit_idempotency_key": "permit-reuse-key",
                "arguments": {},
            }
        )

    await client.close()


@pytest.mark.asyncio
async def test_reuse_with_different_budget_rejected():
    client = B2AClient(api_key="test-key", transport=_transport())
    tool = get_mcp_tools(client, wallet_id="wallet-1")[0]
    await _first_call(tool)

    cached = _permit_requests(tool)
    cached["permit-reuse-key"] = replace(cached["permit-reuse-key"], max_credits=Decimal(999))

    with pytest.raises(ValueError, match="different permit terms"):
        await tool.ainvoke(
            {
                "tool_name": "partner.search",
                "idempotency_key": "invoke-2",
                "permit_idempotency_key": "permit-reuse-key",
                "arguments": {},
            }
        )

    await client.close()


@pytest.mark.asyncio
async def test_reuse_with_different_wallet_rejected():
    client = B2AClient(api_key="test-key", transport=_transport())
    tool = get_mcp_tools(client, wallet_id="wallet-1")[0]
    await _first_call(tool)

    cached = _permit_requests(tool)
    cached["permit-reuse-key"] = replace(cached["permit-reuse-key"], subject_wallet_id="wallet-2")

    with pytest.raises(ValueError, match="different permit terms"):
        await tool.ainvoke(
            {
                "tool_name": "partner.search",
                "idempotency_key": "invoke-2",
                "permit_idempotency_key": "permit-reuse-key",
                "arguments": {},
            }
        )

    await client.close()


@pytest.mark.asyncio
async def test_reuse_with_same_terms_accepted():
    permit_calls = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            permit_calls["count"] += 1
            return httpx.Response(201, json=_permit_payload())
        if request.url.path == "/mcp/messages":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "x",
                    "result": {
                        "content": [{"type": "text", "text": '{"ok": true}'}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )
        return httpx.Response(404)

    client = B2AClient(api_key="test-key", transport=httpx.MockTransport(handler))
    tool = get_mcp_tools(client, wallet_id="wallet-1")[0]
    await _first_call(tool)
    await tool.ainvoke(
        {
            "tool_name": "partner.search",
            "idempotency_key": "invoke-2",
            "permit_idempotency_key": "permit-reuse-key",
            "arguments": {},
        }
    )

    assert permit_calls["count"] == 1

    await client.close()
