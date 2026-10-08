"""Permit expiry and revocation handling for the OpenAI runner's permit records."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from b2a_sdk.errors import PermitDeniedError

from openai_b2a import (
    B2AClient,
    GovernedToolRunner,
    InMemoryOperationKeyStore,
    OperationRecord,
    PermitRecord,
)
from openai_b2a.runner import function_name_for

TOOL = "partner.notes.write"
WALLET = "wallet-1"
PERMIT_KEY = f"oai-permit-run-1-{TOOL}"


def _permit_payload() -> dict:
    now = datetime.now(UTC)
    return {
        "permit_id": "permit-1",
        "issuer_wallet_id": WALLET,
        "subject_wallet_id": WALLET,
        "subject_key_id": "key-1",
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "allowed_tools": [TOOL],
        "max_credits": "100",
        "spent_credits": "0",
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "nonce": "nonce-1",
        "status": "active",
        "signature": "sig-permit-1",
        "key_id": "signing-key-1",
        "issued_at": now.isoformat(),
        "revoked_at": None,
    }


def _receipt_payload(idempotency_key: str) -> dict:
    return {
        "receipt_id": "rcpt-1",
        "idempotency_record_id": "idem-1",
        "permit_id": "permit-1",
        "wallet_id": WALLET,
        "key_id": "key-1",
        "tool": TOOL,
        "request_hash": "a" * 64,
        "response_hash": "b" * 64,
        "ledger_entry_id": "ledger-1",
        "dispatch_attempt_id": None,
        "credits_authorized": "2",
        "credits_charged": "2",
        "outcome": "success",
        "audit_event_id": "audit-1",
        "created_at": datetime.now(UTC).isoformat(),
        "signature": "sig-receipt-1",
        "signature_key_id": "signing-key-1",
        "idempotency_key": idempotency_key,
    }


def _stored_payload(expires_at: str) -> dict:
    """A recorded permit request body, shaped exactly as the runner persists it."""
    return {
        "issuer_wallet_id": WALLET,
        "subject_wallet_id": WALLET,
        "subject_key_id": None,
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "allowed_tools": [TOOL],
        "max_credits": "100",
        "expires_at": expires_at,
    }


def _chat_tool_call(call_id: str):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=function_name_for(TOOL), arguments='{"text": "hi"}'),
    )


def _seeded_store(expires_at: str, permit_id: str | None = None) -> InMemoryOperationKeyStore:
    """A store as left by a run whose permit has since expired."""
    store = InMemoryOperationKeyStore()
    store.put_operation(
        OperationRecord(
            tool_call_id="call_stale",
            tool_name=TOOL,
            idempotency_key="oai-call_stale",
            permit_idempotency_key=PERMIT_KEY,
            permit_id=permit_id,
            wallet_id=WALLET,
        )
    )
    store.put_permit(
        PermitRecord(
            permit_idempotency_key=PERMIT_KEY,
            tool_name=TOOL,
            expires_at=expires_at,
            permit_id=permit_id,
            request_payload=_stored_payload(expires_at),
        )
    )
    return store


@pytest.mark.asyncio
async def test_expired_recorded_permit_fails_before_any_permit_request():
    """A resumed run must not send a request under a key whose expiry passed."""
    plane_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        plane_requests.append(request)
        if request.url.path == "/v1/permits":
            return httpx.Response(201, json=_permit_payload())
        body = json.loads(request.content)
        key = body["params"]["mcpContext"]["idempotency_key"]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": "ok"}],
                    "structuredContent": {"ok": True},
                    "isError": False,
                    "receipt": _receipt_payload(key),
                },
            },
        )

    client = B2AClient(
        api_key="test-key", base_url="http://trust.test", transport=httpx.MockTransport(handler)
    )
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    runner = GovernedToolRunner(
        client, wallet_id=WALLET, run_id="run-1", key_store=_seeded_store(expired)
    )
    runner.register_tool(TOOL, description="Append a note")

    with pytest.raises(ValueError, match="expired"):
        await runner.run(_chat_tool_call("call_stale"))

    assert plane_requests == [], "no request may go out under an expired key"


@pytest.mark.asyncio
async def test_recorded_permit_id_past_expiry_is_not_invoked_with():
    """Even a resolved permit id is refused when the record shows it expired."""
    plane_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        plane_requests.append(request)
        if request.url.path == "/v1/permits":
            return httpx.Response(201, json=_permit_payload())
        body = json.loads(request.content)
        key = body["params"]["mcpContext"]["idempotency_key"]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": "ok"}],
                    "structuredContent": {"ok": True},
                    "isError": False,
                    "receipt": _receipt_payload(key),
                },
            },
        )

    client = B2AClient(
        api_key="test-key", base_url="http://trust.test", transport=httpx.MockTransport(handler)
    )
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    runner = GovernedToolRunner(
        client, wallet_id=WALLET, run_id="run-1", key_store=_seeded_store(expired, "permit-1")
    )
    runner.register_tool(TOOL, description="Append a note")

    with pytest.raises(ValueError, match="expired"):
        await runner.run(_chat_tool_call("call_stale"))

    assert plane_requests == [], "a dead permit id must never reach invoke"


@pytest.mark.asyncio
async def test_revoked_denial_drops_cached_ids_and_replays_identical_body():
    """After a permit_revoked denial the next attempt resolves the permit again."""
    permit_bodies: list[bytes] = []
    invoke_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            permit_bodies.append(request.content)
            return httpx.Response(201, json=_permit_payload())
        invoke_count["count"] += 1
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"message": "permit_revoked"},
            },
        )

    client = B2AClient(
        api_key="test-key", base_url="http://trust.test", transport=httpx.MockTransport(handler)
    )
    store = InMemoryOperationKeyStore()
    runner = GovernedToolRunner(client, wallet_id=WALLET, run_id="run-1", key_store=store)
    runner.register_tool(TOOL, description="Append a note")

    with pytest.raises(PermitDeniedError, match="permit_revoked"):
        await runner.run(_chat_tool_call("call_1"))

    assert store.get_operation("call_1") is not None
    assert store.get_operation("call_1").permit_id is None
    assert store.get_permit(PERMIT_KEY) is not None
    assert store.get_permit(PERMIT_KEY).permit_id is None

    # A later tool call under the same run and tool resolves the permit again,
    # re-sending the identical recorded body under the same key.
    with pytest.raises(PermitDeniedError, match="permit_revoked"):
        await runner.run(_chat_tool_call("call_2"))

    assert len(permit_bodies) == 2, "the dropped permit must be resolved again"
    assert permit_bodies[0] == permit_bodies[1], "the retry must replay the identical body"
    assert invoke_count["count"] == 2
