"""Regression coverage for the JWT bearer path.

`_auth_from_jwt` awaited the synchronous `verify_access_token`, so every
request presenting a valid access token raised TypeError instead of
authenticating — a 500 on the `Bearer ` branch, and a silent fall-through to
API-key auth on the raw-token branch (the `except Exception: pass` there hid
it). The `JWTPayload.exp` annotation claimed `datetime` while PyJWT decodes
epoch ints, which `_exp_to_datetime` then converts.
"""

import pytest

from app.core.auth import get_auth_context
from app.core.config import get_settings
from app.core.jwt import get_jwt_service
from app.routers.auth import _exp_to_datetime


# 32 raw bytes, strict base64 — same non-secret test material CI uses.
TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="


@pytest.fixture
def jwt_service(monkeypatch):
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", TEST_SIGNING_KEY)
    get_settings.cache_clear()
    try:
        yield get_jwt_service()
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_bearer_access_token_authenticates(jwt_service):
    token = jwt_service.create_access_token(
        wallet_id="wallet_test", key_id="key_test", scopes=["billing:read"]
    )

    auth = await get_auth_context(api_key=f"Bearer {token}")

    assert auth.source == "jwt"
    assert auth.wallet_id == "wallet_test"
    assert auth.key_id == "key_test"
    assert auth.is_bootstrap_admin is False


@pytest.mark.anyio
async def test_raw_access_token_authenticates(jwt_service):
    """The non-Bearer branch swallows exceptions — assert it really verifies."""
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw", key_id=None, scopes=[]
    )

    auth = await get_auth_context(api_key=token)

    assert auth.source == "jwt"
    assert auth.wallet_id == "wallet_raw"


def test_payload_exp_is_epoch_seconds(jwt_service):
    """`_exp_to_datetime` takes epoch ints; the payload must supply them."""
    payload = jwt_service.verify_refresh_token(
        jwt_service.create_refresh_token(wallet_id="wallet_exp")
    )

    assert isinstance(payload.exp, int)
    assert isinstance(payload.iat, int)
    assert _exp_to_datetime(payload.exp).tzinfo is not None
