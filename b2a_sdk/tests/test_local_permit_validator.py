"""LocalPermitValidator + GovernedEdgeSession unit tests.

Self-contained: the "server" here is an in-test Ed25519 key signing a
hand-built mirror of the trust plane's permit signing payload (the byte
construction in ``app/services/permits.py`` — rebuilt independently in
``_build_signed_permit`` rather than via the code under test, so a drift in
the validator's reconstruction fails these tests instead of verifying
itself). No imports from ``app/``; HTTP is ``httpx.MockTransport``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest

from b2a_sdk.client import AgentMiddlewareClient
from b2a_sdk.edge_client import GovernedEdgeSession, LocalPermitValidator
from b2a_sdk.errors import PermitDeniedError
from b2a_sdk.receipt_verifier import key_set_from_document

KID = "local-validator-test-ed25519"
TOOL = "partner.search"


def _canonical(payload: dict[str, Any]) -> str:
    """The awi-canonical-json/1 byte rules (all values already strings/ints)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _permit_dict(**overrides: Any) -> dict[str, Any]:
    """An API-shaped permit dict (unsigned) for pure check() tests."""
    now = datetime.now(timezone.utc)
    permit: dict[str, Any] = {
        "permit_id": "permit-local-1",
        "issuer_wallet_id": "wallet-1",
        "subject_wallet_id": "wallet-1",
        "subject_key_id": "key-1",
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "allowed_tools": [TOOL],
        "max_credits": "50",
        "spent_credits": "0",
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "nonce": "nonce-1",
        "status": "active",
        "requires_human_approval": False,
        "signature": base64.b64encode(b"\x00" * 64).decode(),
        "key_id": KID,
        "issued_at": now.isoformat(),
        "revoked_at": None,
        "max_calls_per_tool": {},
        "aggregate_value_cap": None,
        "forbidden_fields": [],
        "recipient_domain": None,
    }
    permit.update(overrides)
    return permit


def _build_signed_permit(
    *,
    requires_human_approval: bool = False,
    max_calls_per_tool: dict[str, int] | None = None,
    aggregate_value_cap: str | None = None,
    forbidden_fields: list[str] | None = None,
    recipient_domain: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (api-shaped permit dict, trust-keys document), genuinely signed.

    Independent byte-level mirror of the server's signing construction:
    base fields, conditional ``requires_human_approval`` / v2 fields only
    when set, then ``alg``/``kid`` folded in and ``payload_hash`` computed
    over the payload-so-far, then Ed25519 over the canonical JSON.
    """
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    issued = datetime.now(timezone.utc).replace(microsecond=123456)
    expires = issued + timedelta(minutes=30)

    signing_payload: dict[str, Any] = {
        "permit_id": "permit-local-1",
        "issuer_wallet_id": "wallet-1",
        "subject_wallet_id": "wallet-1",
        "subject_key_id": "key-1",
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "allowed_tools": [TOOL],
        "max_credits": "50",
        "expires_at": expires.isoformat(),
        "nonce": "nonce-1",
        "status": "active",
        "issued_at": issued.isoformat(),
        "alg": "Ed25519",
        "kid": KID,
    }
    if requires_human_approval:
        signing_payload["requires_human_approval"] = True
    if max_calls_per_tool:
        signing_payload["max_calls_per_tool"] = max_calls_per_tool
    if aggregate_value_cap is not None:
        signing_payload["aggregate_value_cap"] = aggregate_value_cap
    if forbidden_fields:
        signing_payload["forbidden_fields"] = forbidden_fields
    if recipient_domain:
        signing_payload["recipient_domain"] = recipient_domain
    signing_payload["payload_hash"] = hashlib.sha256(
        _canonical(signing_payload).encode()
    ).hexdigest()
    signature = private_key.sign(_canonical(signing_payload).encode())

    permit = _permit_dict(
        expires_at=expires.isoformat(),
        issued_at=issued.isoformat(),
        requires_human_approval=requires_human_approval,
        max_calls_per_tool=dict(max_calls_per_tool or {}),
        aggregate_value_cap=aggregate_value_cap,
        forbidden_fields=list(forbidden_fields or []),
        recipient_domain=recipient_domain,
        signature=base64.b64encode(signature).decode(),
    )
    key_document = {
        "schema_version": "1.0",
        "alg": "Ed25519",
        "keys": [
            {
                "kid": KID,
                "alg": "Ed25519",
                "status": "active",
                "public_key_b64": base64.b64encode(
                    private_key.public_key().public_bytes_raw()
                ).decode(),
            }
        ],
    }
    return permit, key_document


def _validator(
    permit: dict[str, Any], key_document: dict[str, Any]
) -> LocalPermitValidator:
    return LocalPermitValidator(permit, key_set_from_document(key_document))


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_verify_permit_accepts_genuine_signature():
    permit, key_document = _build_signed_permit()
    assert _validator(permit, key_document).verify_permit() is True


def test_verify_permit_normalizes_api_value_forms():
    """Naive timestamps and non-normalized decimals canonicalize identically.

    The API serializes the DB's naive-UTC datetimes without an offset and may
    render decimals with trailing zeros; both must map to the same signed
    bytes as the creation-time values.
    """
    permit, key_document = _build_signed_permit()
    reshaped = dict(permit)
    reshaped["expires_at"] = permit["expires_at"].replace("+00:00", "")
    reshaped["issued_at"] = permit["issued_at"].replace("+00:00", "")
    reshaped["max_credits"] = "50.00000000"
    assert _validator(reshaped, key_document).verify_permit() is True


def test_verify_permit_covers_exactly_the_signed_fields():
    """Tampering any signed field fails; unsigned fields never affect it.

    The signature covers: permit_id, issuer/subject wallet ids,
    subject_key_id, scopes, allowed_tools, max_credits, expires_at, nonce,
    issued_at, the signing kid (key_id), and — only when set —
    requires_human_approval plus the v2 constraints. It deliberately does
    NOT cover spent_credits (mutable server spend state, enforced by the
    atomic budget guard) or the stored status (revocation is enforced by
    validation with status hardcoded "active" in the payload).
    """
    permit, key_document = _build_signed_permit()

    signed_field_tampers: dict[str, Any] = {
        "permit_id": "permit-other",
        "issuer_wallet_id": "wallet-other",
        "subject_wallet_id": "wallet-other",
        "subject_key_id": "key-other",
        "scopes": ["tool:other:invoke", "billing:charge"],
        "allowed_tools": ["other.tool"],
        "max_credits": "500000",
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=365)
        ).isoformat(),
        "nonce": "nonce-forged",
        "issued_at": (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat(),
        "key_id": "some-other-kid",
        # Signed only when true: flipping the stored flag in either
        # direction changes the rebuilt payload.
        "requires_human_approval": True,
    }
    for field, forged_value in signed_field_tampers.items():
        tampered = dict(permit)
        tampered[field] = forged_value
        validator = _validator(tampered, key_document)
        assert validator.verify_permit() is False, f"{field} must be signed"

    unsigned_field_tampers: dict[str, Any] = {
        "spent_credits": "49",
        "status": "revoked",
        "revoked_at": datetime.now(timezone.utc).isoformat(),
    }
    for field, new_value in unsigned_field_tampers.items():
        changed = dict(permit)
        changed[field] = new_value
        validator = _validator(changed, key_document)
        assert validator.verify_permit() is True, f"{field} is not signed"


def test_verify_permit_covers_v2_constraints_when_present():
    permit, key_document = _build_signed_permit(
        requires_human_approval=True,
        max_calls_per_tool={TOOL: 3},
        aggregate_value_cap="10.5",
        forbidden_fields=["secret_token"],
        recipient_domain="partner.example.com",
    )
    assert _validator(permit, key_document).verify_permit() is True

    v2_tampers: dict[str, Any] = {
        "max_calls_per_tool": {TOOL: 30000},
        "aggregate_value_cap": "999999",
        "forbidden_fields": [],
        "recipient_domain": "attacker.example.com",
        "requires_human_approval": False,
    }
    for field, forged_value in v2_tampers.items():
        tampered = dict(permit)
        tampered[field] = forged_value
        validator = _validator(tampered, key_document)
        assert validator.verify_permit() is False, f"{field} must be signed"


def test_verify_permit_fails_closed_on_unknown_key_and_malformed_input():
    permit, key_document = _build_signed_permit()
    # Key set that does not hold the signing kid.
    other_doc = {
        "keys": [
            {
                "kid": "different-kid",
                "alg": "Ed25519",
                "status": "active",
                "public_key_b64": key_document["keys"][0]["public_key_b64"],
            }
        ]
    }
    assert _validator(permit, other_doc).verify_permit() is False
    # Malformed permit material returns False rather than raising.
    validator = _validator(permit, key_document)
    assert validator.verify_permit({"permit_id": "only-this"}) is False
    broken = dict(permit)
    broken["signature"] = "not-base64!"
    assert validator.verify_permit(broken) is False
    broken = dict(permit)
    broken["max_credits"] = "not-a-decimal"
    assert validator.verify_permit(broken) is False


# ---------------------------------------------------------------------------
# In-process checks (no signature, no network)
# ---------------------------------------------------------------------------


def test_check_uses_server_reason_strings_for_denials():
    key_set: dict[str, bytes] = {}
    now = datetime.now(timezone.utc)

    expired = LocalPermitValidator(_permit_dict(), key_set)
    decision = expired.check(TOOL, Decimal("1"), now=now + timedelta(hours=2))
    assert decision.allowed is False
    assert decision.reason == "permit_expired"

    revoked = LocalPermitValidator(_permit_dict(status="revoked"), key_set)
    decision = revoked.check(TOOL, Decimal("1"))
    assert decision.allowed is False
    assert decision.reason == "permit_revoked"

    validator = LocalPermitValidator(_permit_dict(), key_set)
    decision = validator.check("some.other.tool", Decimal("1"))
    assert decision.allowed is False
    assert decision.reason == "permit_tool_not_allowed"

    no_billing = LocalPermitValidator(
        _permit_dict(scopes=[f"tool:{TOOL}:invoke"]), key_set
    )
    decision = no_billing.check(TOOL, Decimal("1"))
    assert decision.allowed is False
    assert decision.reason == "permit_scope_missing"

    over_budget = LocalPermitValidator(
        _permit_dict(max_credits="10", spent_credits="8"), key_set
    )
    decision = over_budget.check(TOOL, Decimal("3"))
    assert decision.allowed is False
    assert decision.reason == "permit_budget_exceeded"
    assert over_budget.check(TOOL, Decimal("2")).allowed is True

    capped = LocalPermitValidator(
        _permit_dict(max_calls_per_tool={TOOL: 1}), key_set
    )
    assert capped.check(TOOL, Decimal("1")).allowed is True
    capped.record_use(TOOL, Decimal("1"))
    decision = capped.check(TOOL, Decimal("1"))
    assert decision.allowed is False
    assert decision.reason == "permit_max_calls_exceeded"

    allowed = LocalPermitValidator(_permit_dict(), key_set).check(TOOL, Decimal("1"))
    assert allowed.allowed is True
    assert allowed.reason is None


def test_record_use_advances_local_reservation_and_counters():
    validator = LocalPermitValidator(
        _permit_dict(max_credits="10", spent_credits="4"), {}
    )
    assert validator.check(TOOL, Decimal("6")).allowed is True
    validator.record_use(TOOL, Decimal("6"))
    assert validator.reserved_credits == Decimal("6")
    assert validator.call_counts == {TOOL: 1}
    # max(10) - spent(4) - reserved(6) leaves nothing.
    denied = validator.check(TOOL, Decimal("0.00000001"))
    assert denied.allowed is False
    assert denied.reason == "permit_budget_exceeded"
    assert validator.check(TOOL, Decimal("0")).allowed is True


# ---------------------------------------------------------------------------
# GovernedEdgeSession over MockTransport
# ---------------------------------------------------------------------------


def _receipt_payload(credits_charged: str = "2") -> dict[str, Any]:
    return {
        "receipt_id": "receipt-local-1",
        "permit_id": "permit-local-1",
        "wallet_id": "wallet-1",
        "key_id": "key-1",
        "tool": TOOL,
        "request_hash": "a" * 64,
        "response_hash": "b" * 64,
        "ledger_entry_id": "ledger-1",
        "dispatch_attempt_id": "dispatch-1",
        "credits_authorized": credits_charged,
        "credits_charged": credits_charged,
        "outcome": "success",
        "audit_event_id": "audit-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signature": "receipt-signature",
        "signature_key_id": KID,
    }


@pytest.mark.asyncio
async def test_session_open_verifies_and_local_denial_skips_the_server():
    permit, key_document = _build_signed_permit()
    invoke_posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal invoke_posts
        if request.url.path == "/v1/permits/permit-local-1":
            return httpx.Response(200, json=permit)
        if request.url.path == "/.well-known/trust-keys.json":
            return httpx.Response(200, json=key_document)
        if request.url.path == "/mcp/messages":
            invoke_posts += 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "session-invoke-1",
                    "result": {
                        "content": [{"type": "text", "text": '{"ok": true}'}],
                        "structuredContent": {"ok": True},
                        "isError": False,
                        "receipt": _receipt_payload(),
                    },
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = AgentMiddlewareClient(
        api_key="test-key",
        base_url="https://gateway.example",
        transport=httpx.MockTransport(handler),
    )
    try:
        session = await GovernedEdgeSession.open(
            client, permit_id="permit-local-1", wallet_id="wallet-1"
        )
        assert session.validator.verify_permit() is True

        # Local denial: the out-of-scope tool never reaches the server —
        # that is the RPC hop the in-process validator eliminates.
        with pytest.raises(PermitDeniedError) as exc_info:
            await session.invoke(
                "some.other.tool", {}, idempotency_key="session-denied-1"
            )
        assert exc_info.value.reason == "permit_tool_not_allowed"
        assert invoke_posts == 0

        # Allowed call goes through the governed loop and records local use.
        result = await session.invoke(
            TOOL,
            {"query": "risk"},
            idempotency_key="session-invoke-1",
            estimated_credits=Decimal("2"),
        )
        assert invoke_posts == 1
        assert result.receipt.credits_charged == Decimal("2")
        assert session.validator.reserved_credits == Decimal("2")
        assert session.validator.call_counts == {TOOL: 1}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_session_open_rejects_a_permit_the_published_keys_cannot_verify():
    permit, key_document = _build_signed_permit()
    _, other_document = _build_signed_permit()  # different key material

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits/permit-local-1":
            return httpx.Response(200, json=permit)
        if request.url.path == "/.well-known/trust-keys.json":
            return httpx.Response(200, json=other_document)
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = AgentMiddlewareClient(
        api_key="test-key",
        base_url="https://gateway.example",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(PermitDeniedError) as exc_info:
            await GovernedEdgeSession.open(
                client, permit_id="permit-local-1", wallet_id="wallet-1"
            )
        assert exc_info.value.reason == "permit_signature_invalid"
    finally:
        await client.close()
