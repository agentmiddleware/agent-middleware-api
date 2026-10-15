"""Per-instance isolation of the permit cache between tool instances."""

from datetime import UTC, datetime

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


@pytest.mark.asyncio
async def test_permit_cache_is_not_shared_between_instances():
    """A cached permit_id must never leak from one tool instance to another."""
    permit_create_count = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            permit_create_count["count"] += 1
            return httpx.Response(201, json=_permit_payload())

        if request.url.path == "/mcp/messages":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "isolation-test",
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
    first = CrewAIB2ATool(api_key="test-key", wallet_id="wallet-1")
    first.client = base_client
    second = CrewAIB2ATool(api_key="test-key", wallet_id="wallet-1")
    second.client = base_client

    result1 = await first._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="invoke-1",
        permit_idempotency_key="shared-permit-key",
        arguments={},
    )
    result2 = await second._arun(
        operation="call_tool",
        tool_name="partner.search",
        idempotency_key="invoke-2",
        permit_idempotency_key="shared-permit-key",
        arguments={},
    )

    # The second instance must create its own permit: reusing the first
    # instance's cached permit_id would charge against the wrong permit.
    assert permit_create_count["count"] == 2
    assert "receipt-success" in result1
    assert "receipt-success" in result2

    await base_client.close()
