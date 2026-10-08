"""Permit cache expiry and revocation handling for the LangChain wrapper."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from b2a_sdk.errors import PermitDeniedError

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
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
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
        "created_at": datetime.now(UTC).isoformat(),
        "signature": f"sig-{outcome}",
        "signature_key_id": "signing-key-1",
    }


def _success_handler(counters):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            counters["permit"] += 1
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            counters["invoke"] += 1
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

    return handler


@pytest.mark.asyncio
async def test_expired_cached_permit_is_resolved_again():
    """A cached permit read past its own expiry must not be reused.

    With a zero-minute TTL every entry is born expired, so each call resolves
    the permit again instead of reusing the cached id.
    """
    counters = {"permit": 0, "invoke": 0}
    transport = httpx.MockTransport(_success_handler(counters))
    client = B2AClient(api_key="test-key", transport=transport)
    tool = get_mcp_tools(client, wallet_id="wallet-1", permit_ttl_minutes=0)[0]

    for i in ("invoke-1", "invoke-2"):
        result = await tool.ainvoke(
            {
                "tool_name": "partner.search",
                "idempotency_key": i,
                "permit_idempotency_key": "permit-expiry-test",
                "arguments": {},
            }
        )
        assert "receipt-success" in result

    assert counters["permit"] == 2, "an expired cached permit must be resolved again"
    assert counters["invoke"] == 2

    await client.close()


@pytest.mark.asyncio
async def test_revoked_permit_denial_drops_cached_permit():
    """An invoke denied with permit_revoked must drop the cached permit id."""
    counters = {"permit": 0, "invoke": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            counters["permit"] += 1
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            counters["invoke"] += 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "revoked-test",
                    "error": {"code": -32003, "message": "permit_revoked"},
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = B2AClient(api_key="test-key", transport=transport)
    tool = get_mcp_tools(client, wallet_id="wallet-1")[0]

    with pytest.raises(PermitDeniedError, match="permit_revoked"):
        await tool.ainvoke(
            {
                "tool_name": "partner.search",
                "idempotency_key": "invoke-1",
                "permit_idempotency_key": "permit-revoked-test",
                "arguments": {},
            }
        )

    # The cached id was dropped: the retry resolves the permit again instead
    # of reusing a permit the server already reported as revoked.
    with pytest.raises(PermitDeniedError, match="permit_revoked"):
        await tool.ainvoke(
            {
                "tool_name": "partner.search",
                "idempotency_key": "invoke-2",
                "permit_idempotency_key": "permit-revoked-test",
                "arguments": {},
            }
        )

    assert counters["permit"] == 2, "a revoked cached permit must be resolved again"
    assert counters["invoke"] == 2

    await client.close()
