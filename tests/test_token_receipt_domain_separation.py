"""Domain separation between JWT login tokens and signed receipts.

The trust-plane Ed25519 key signs both JWT access/refresh tokens
(``app.core.jwt``) and canonical-JSON receipt payloads
(``app.services.receipts``). These tests pin both directions of that
boundary: receipt-shaped claims are never login tokens, and login-token
claims never verify as receipt payloads, while receipts minted before the
domain label keep verifying.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt as pyjwt
import pytest

from app.core.config import get_settings
from app.core.jwt import (
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWTError,
    get_jwt_service,
)
from app.db.database import get_session_factory
from app.db.models import ReceiptModel
from app.services.receipts import ReceiptService
from app.services.signing_keys import RECEIPT_AUDIENCE, get_signing_key_service


# 32 raw bytes, strict base64. Same non-secret test material CI uses.
TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="


@pytest.fixture
def jwt_service(monkeypatch):
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", TEST_SIGNING_KEY)
    get_settings.cache_clear()
    try:
        yield get_jwt_service()
    finally:
        get_settings.cache_clear()


def _receipt_model(**overrides) -> ReceiptModel:
    fields = dict(
        receipt_id="rcpt_domain_0001",
        idempotency_record_id="idem_domain_0001",
        dispatch_attempt_id="disp_domain_0001",
        permit_id="pmt_domain_0001",
        wallet_id="agt-domain-0001",
        key_id="key_domain_0001",
        tool="domain-echo",
        request_hash="a" * 64,
        response_hash="b" * 64,
        ledger_entry_id="led_domain_0001",
        credits_authorized=Decimal("2.5"),
        credits_charged=Decimal("2.5"),
        outcome="success",
        reason_code=None,
        audit_event_id="aud_domain_0001",
        approval_id=None,
        constraints_evaluated_json=None,
        created_at=datetime(2026, 9, 14, 17, 0, 0, tzinfo=timezone.utc),
        signature="",
        signature_key_id="",
    )
    fields.update(overrides)
    return ReceiptModel(**fields)


async def _sign_like_create(model: ReceiptModel, *, include_domain: bool) -> None:
    """Sign a model the way ``create_receipt`` does, with or without the label."""
    signing_keys = get_signing_key_service()
    key = await signing_keys.ensure_active_key()
    payload = ReceiptService._verification_payload(
        model, include_linkage=True, include_domain=include_domain
    )
    unsigned = {
        name: value
        for name, value in payload.items()
        if name not in {"alg", "kid", "payload_hash"}
    }
    signature, key_id, _ = signing_keys.sign_payload_with_key_id(unsigned, key.key_id)
    model.signature = signature
    model.signature_key_id = key_id


def test_receipt_shaped_access_token_is_not_a_login_token(jwt_service):
    """A validly signed access token carrying receipt claims must be refused.

    Without the domain check this token verifies as a login token, because
    every claim the token verifier requires is present and the signature is
    from the deployment's own key.
    """
    private_key, _ = jwt_service._load_keys()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "wallet_domain",
        "key_id": "key_domain",
        "scopes": [],
        "iat": now,
        "exp": now + timedelta(seconds=900),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": "jwt-domain-0001",
        "type": "access",
        "receipt_id": "rcpt_domain_0001",
    }
    token = pyjwt.encode(claims, private_key, algorithm=JWT_ALGORITHM)

    with pytest.raises(JWTError, match="token_receipt_domain_mismatch"):
        jwt_service.verify_access_token(token)


def test_plain_access_and_refresh_tokens_still_verify(jwt_service):
    """The domain check must not break tokens without receipt claims."""
    access = jwt_service.create_access_token(
        wallet_id="wallet_domain", key_id="key_domain", scopes=[]
    )
    assert jwt_service.verify_access_token(access).sub == "wallet_domain"

    refresh = jwt_service.create_refresh_token(wallet_id="wallet_domain")
    assert jwt_service.verify_refresh_token(refresh).type == "refresh"


async def test_login_token_claims_do_not_verify_as_receipt_payload(clean_database):
    """Token claims signed by the shared key must fail receipt verification.

    The signature here is genuinely valid for these bytes; only the domain
    guard makes verification refuse them.
    """
    signing_keys = get_signing_key_service()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "wallet_domain",
        "key_id": "key_domain",
        "scopes": [],
        "iat": now,
        "exp": now + timedelta(seconds=900),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": "jwt-domain-0002",
        "type": "access",
    }
    signature, key_id, payload_hash = await signing_keys.sign_payload(claims)
    signed = {
        **claims,
        "alg": "Ed25519",
        "kid": key_id,
        "payload_hash": payload_hash,
    }

    assert (
        await signing_keys.verify_payload(signed, signature=signature, key_id=key_id)
        is False
    )


def test_domain_label_is_additive_only():
    """The label adds exactly one covered claim to the receipt payload."""
    model = _receipt_model()
    labeled = ReceiptService._verification_payload(
        model, include_linkage=True, include_domain=True
    )
    unlabeled = ReceiptService._verification_payload(model, include_linkage=True)
    labeled_hash = labeled.pop("payload_hash")
    unlabeled_hash = unlabeled.pop("payload_hash")
    assert labeled == {**unlabeled, "aud": RECEIPT_AUDIENCE}
    assert labeled_hash != unlabeled_hash


async def test_new_domain_labeled_receipt_verifies(clean_database):
    """A receipt minted with the domain label verifies and exports it."""
    model = _receipt_model()
    await _sign_like_create(model, include_domain=True)

    factory = get_session_factory()
    async with factory() as session:
        assert await ReceiptService().verify_model(model, session=session) is True
        signing_input = await ReceiptService().signing_input_for_model(
            model, session=session
        )
    assert signing_input is not None
    assert json.loads(signing_input)["aud"] == RECEIPT_AUDIENCE


async def test_historic_unlabeled_receipt_still_verifies(clean_database):
    """A receipt minted before the label keeps verifying without it."""
    model = _receipt_model(receipt_id="rcpt_domain_0002")
    await _sign_like_create(model, include_domain=False)

    factory = get_session_factory()
    async with factory() as session:
        assert await ReceiptService().verify_model(model, session=session) is True
        signing_input = await ReceiptService().signing_input_for_model(
            model, session=session
        )
    assert signing_input is not None
    assert "aud" not in json.loads(signing_input)
