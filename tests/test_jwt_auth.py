"""Regression coverage for JWT bearer authentication."""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import AuthContext, get_auth_context
from app.core.config import get_settings
from app.core.jwt import (
    JWT_ACCESS_EXPIRY,
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_DOMAIN,
    JWT_ISSUER,
    JWT_TYPE,
    JWTError,
    get_jwt_service,
)
from app.routers.auth import _exp_to_datetime


# 32 raw bytes, strict base64 — same non-secret test material CI uses.
TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="

auth_app = FastAPI()


@auth_app.get("/protected")
async def protected(auth: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "source": auth.source,
        "wallet_id": auth.wallet_id,
        "key_id": auth.key_id,
        "is_bootstrap_admin": auth.is_bootstrap_admin,
    }


@pytest.fixture
def jwt_service(monkeypatch):
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", TEST_SIGNING_KEY)
    get_settings.cache_clear()
    try:
        yield get_jwt_service()
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def auth_client():
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def live_key(monkeypatch):
    from app.services.api_key_service import APIKeyService

    async def is_key_live(_self, _key_id: str, _wallet_id: str) -> bool:
        return True

    monkeypatch.setattr(APIKeyService, "consume_derived_key_use", is_key_live)


@pytest.mark.anyio
async def test_bearer_access_token_authenticates(jwt_service, live_key):
    token = jwt_service.create_access_token(
        wallet_id="wallet_test", key_id="key_test", scopes=["billing:read"]
    )

    auth = await get_auth_context(api_key=f"Bearer {token}")

    assert auth.source == "jwt"
    assert auth.wallet_id == "wallet_test"
    assert auth.key_id == "key_test"
    assert auth.is_bootstrap_admin is False


@pytest.mark.anyio
async def test_raw_access_token_authenticates(jwt_service, live_key):
    """The non-Bearer branch must really verify, not just accept the shape."""
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw", key_id="key_raw", scopes=[]
    )

    auth = await get_auth_context(api_key=token)

    assert auth.source == "jwt"
    assert auth.wallet_id == "wallet_raw"


@pytest.mark.anyio
async def test_jwt_contexts_do_not_share_raw_key(jwt_service, live_key):
    """Legacy routers key resource ownership on ``raw_key``. Every EdDSA token
    starts with the same encoded header, so a truncated token made every JWT
    caller in every wallet the same principal there."""
    first = jwt_service.create_access_token(
        wallet_id="wallet_one", key_id="key_one", scopes=[]
    )
    second = jwt_service.create_access_token(
        wallet_id="wallet_two", key_id="key_two", scopes=[]
    )
    assert first[:20] == second[:20]

    one = await get_auth_context(api_key=None, authorization=f"Bearer {first}")
    two = await get_auth_context(api_key=second)

    assert one.raw_key != two.raw_key
    # The handle is stable per originating key and carries no token material.
    again = await get_auth_context(api_key=None, authorization=f"Bearer {first}")
    assert again.raw_key == one.raw_key
    assert first[:20] not in one.raw_key
    assert second[:20] not in two.raw_key


@pytest.mark.anyio
async def test_raw_unbound_access_token_fails_closed(jwt_service, auth_client):
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw_unbound", key_id=None, scopes=[]
    )

    response = await auth_client.get(
        "/protected",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "unbound_access_token"


@pytest.mark.anyio
async def test_raw_revoked_access_token_fails_closed(
    jwt_service, auth_client, monkeypatch
):
    from app.services.api_key_service import APIKeyService

    async def is_key_live(_self, _key_id: str, _wallet_id: str) -> bool:
        return False

    monkeypatch.setattr(APIKeyService, "consume_derived_key_use", is_key_live)
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw_revoked", key_id="key_revoked", scopes=[]
    )

    response = await auth_client.get(
        "/protected",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "no_active_api_key"


@pytest.mark.anyio
async def test_raw_rejected_token_cannot_fall_through_to_configured_env_key(
    jwt_service, auth_client, monkeypatch
):
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw_configured", key_id=None, scopes=[]
    )
    monkeypatch.setenv("VALID_API_KEYS", token)
    get_settings.cache_clear()

    response = await auth_client.get(
        "/protected",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "unbound_access_token"


@pytest.mark.anyio
async def test_raw_rejected_token_cannot_fall_through_to_debug_bootstrap(
    jwt_service, auth_client, monkeypatch
):
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw_debug", key_id=None, scopes=[]
    )
    monkeypatch.setenv("VALID_API_KEYS", "")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    response = await auth_client.get(
        "/protected",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "unbound_access_token"


@pytest.mark.anyio
async def test_unbound_access_token_fails_closed(jwt_service, auth_client):
    token = jwt_service.create_access_token(
        wallet_id="wallet_unbound", key_id=None, scopes=[]
    )

    response = await auth_client.get(
        "/protected",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "unbound_access_token"


@pytest.mark.anyio
async def test_http_bearer_access_token_takes_priority_over_api_key(
    jwt_service, auth_client, live_key
):
    token = jwt_service.create_access_token(
        wallet_id="wallet_http", key_id="key_http", scopes=["billing:read"]
    )

    response = await auth_client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Key": "test-key",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": "jwt",
        "wallet_id": "wallet_http",
        "key_id": "key_http",
        "is_bootstrap_admin": False,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "authorization",
    [
        "Basic opaque",
        "Bearer",
        "Bearer ",
        "Bearer  opaque",
        "Bearer opaque extra",
        "bearer opaque",
    ],
)
async def test_malformed_authorization_does_not_fall_back_to_api_key(
    authorization, auth_client
):
    response = await auth_client.get(
        "/protected",
        headers={"Authorization": authorization, "X-API-Key": "test-key"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_token"


@pytest.mark.anyio
async def test_invalid_bearer_does_not_fall_back_to_api_key(auth_client):
    response = await auth_client.get(
        "/protected",
        headers={
            "Authorization": "Bearer not-a-signed-token",
            "X-API-Key": "test-key",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_token"


@pytest.mark.anyio
async def test_refresh_bearer_does_not_fall_back_to_api_key(jwt_service, auth_client):
    refresh_token = jwt_service.create_refresh_token(wallet_id="wallet_refresh")

    response = await auth_client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {refresh_token}",
            "X-API-Key": "test-key",
        },
    )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_token"
    assert "token_type_mismatch" in detail["message"]


@pytest.mark.anyio
async def test_http_x_api_key_remains_supported(auth_client):
    response = await auth_client.get(
        "/protected",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "env"
    assert response.json()["is_bootstrap_admin"] is True


def test_payload_exp_is_epoch_seconds(jwt_service):
    """`_exp_to_datetime` takes epoch ints; the payload must supply them."""
    payload = jwt_service.verify_refresh_token(
        jwt_service.create_refresh_token(wallet_id="wallet_exp")
    )

    assert isinstance(payload.exp, int)
    assert isinstance(payload.iat, int)
    assert _exp_to_datetime(payload.exp).tzinfo is not None


def _signed_access_token_without(jwt_service, claim: str) -> str:
    """Sign an otherwise valid, bound access token that omits one claim.

    Uses the deployment's own signing key, so the only thing wrong with the
    token is the missing claim.
    """
    private_key, signing_key_id = jwt_service._load_keys()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "wallet_missing_claim",
        "key_id": "key_missing_claim",
        "scopes": [],
        "iat": now,
        "exp": now + timedelta(seconds=JWT_ACCESS_EXPIRY),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": "jwt-missing-claim",
        "type": "access",
        "dom": JWT_DOMAIN,
    }
    del claims[claim]
    return pyjwt.encode(
        claims,
        private_key,
        algorithm=JWT_ALGORITHM,
        headers={"kid": signing_key_id, "typ": JWT_TYPE},
    )


@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "jti"])
def test_signed_token_missing_a_required_claim_is_refused(jwt_service, claim):
    """A validly signed token without ``exp`` must not be a forever-token.

    The other claims are read by ``JWTPayload``; without them a token used to
    surface as a ``KeyError`` rather than a refused credential.
    """
    token = _signed_access_token_without(jwt_service, claim)

    with pytest.raises(JWTError, match=f"invalid_token: .*{claim}"):
        jwt_service.verify_access_token(token)


@pytest.mark.anyio
@pytest.mark.parametrize("header", ["Authorization", "X-API-Key"])
async def test_token_without_exp_is_401_on_both_header_paths(
    jwt_service, auth_client, live_key, header
):
    token = _signed_access_token_without(jwt_service, "exp")
    value = f"Bearer {token}" if header == "Authorization" else token

    response = await auth_client.get("/protected", headers={header: value})

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_token"
    assert "exp" in detail["message"]


class _KeyStoreUnavailable(Exception):
    """Stand-in for an unexpected failure while checking key liveness."""


@pytest.fixture
def key_store_down(monkeypatch):
    from app.services.api_key_service import APIKeyService

    async def is_key_live(_self, _key_id: str, _wallet_id: str) -> bool:
        raise _KeyStoreUnavailable("key store unavailable")

    monkeypatch.setattr(APIKeyService, "consume_derived_key_use", is_key_live)


@pytest.mark.anyio
async def test_raw_token_failure_is_not_masked_as_an_api_key_lookup(
    jwt_service, key_store_down
):
    """A JWT in X-API-Key fails the same way it does as a bearer.

    The raw-token branch used to swallow any non-HTTP exception and retry the
    token as an API key, which turned a liveness check that could not run
    into a misleading ``403 invalid_api_key``.
    """
    token = jwt_service.create_access_token(
        wallet_id="wallet_store_down", key_id="key_store_down", scopes=[]
    )

    with pytest.raises(_KeyStoreUnavailable):
        await get_auth_context(api_key=None, authorization=f"Bearer {token}")
    with pytest.raises(_KeyStoreUnavailable):
        await get_auth_context(api_key=token)


@pytest.mark.anyio
async def test_raw_token_failure_cannot_fall_through_to_debug_bootstrap(
    jwt_service, key_store_down, monkeypatch
):
    """With no keys configured, falling through meant a bootstrap admin."""
    token = jwt_service.create_access_token(
        wallet_id="wallet_store_down_debug", key_id="key_store_down", scopes=[]
    )
    monkeypatch.setenv("VALID_API_KEYS", "")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    with pytest.raises(_KeyStoreUnavailable):
        await get_auth_context(api_key=token)


def _login_claims(token_type: str) -> dict:
    """Claims a login token needs, including the domain label."""
    now = datetime.now(timezone.utc)
    expiry = JWT_ACCESS_EXPIRY if token_type == "access" else 3600
    claims = {
        "sub": "wallet_domain",
        "scopes": [],
        "iat": now,
        "exp": now + timedelta(seconds=expiry),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": f"jwt-domain-{token_type}",
        "type": token_type,
        "dom": JWT_DOMAIN,
    }
    if token_type == "access":
        claims["key_id"] = "key_domain"
    return claims


def _verify_login(jwt_service, token: str, token_type: str):
    if token_type == "access":
        return jwt_service.verify_access_token(token)
    return jwt_service.verify_refresh_token(token)


@pytest.mark.parametrize("token_type", ["access", "refresh"])
def test_trust_plane_key_cannot_mint_a_login_token(jwt_service, token_type):
    """A signature from the receipt key must not authenticate a caller.

    Login tokens used to be signed with the same private key as permits and
    receipts. A token built that way, even with the login domain label and a
    header key id, still verified.
    """
    from app.services.signing_keys import _decode_private_key

    trust_key = _decode_private_key(TEST_SIGNING_KEY)
    token = pyjwt.encode(
        _login_claims(token_type),
        trust_key,
        algorithm=JWT_ALGORITHM,
        headers={"kid": "ed25519-trust-plane", "typ": JWT_TYPE},
    )

    with pytest.raises(JWTError):
        _verify_login(jwt_service, token, token_type)


def test_login_signature_does_not_verify_under_the_trust_plane_key(jwt_service):
    """The bytes of a login token must not be a trust-plane signature."""
    import base64

    from cryptography.exceptions import InvalidSignature
    from app.services.signing_keys import _decode_private_key

    token = jwt_service.create_access_token(
        wallet_id="wallet_separated", key_id="key_separated", scopes=[]
    )
    signing_input, signature_b64 = token.rsplit(".", 1)
    signature = base64.urlsafe_b64decode(
        signature_b64 + "=" * (-len(signature_b64) % 4)
    )
    trust_public = _decode_private_key(TEST_SIGNING_KEY).public_key()

    with pytest.raises(InvalidSignature):
        trust_public.verify(signature, signing_input.encode("ascii"))


@pytest.mark.parametrize("token_type", ["access", "refresh"])
def test_login_token_key_id_is_in_the_header(jwt_service, token_type):
    """The signing key id is a protected header, not a body field."""
    if token_type == "access":
        token = jwt_service.create_access_token(
            wallet_id="wallet_header", key_id="key_header", scopes=["billing:read"]
        )
    else:
        token = jwt_service.create_refresh_token(
            wallet_id="wallet_header", scopes=["billing:read"]
        )

    header = pyjwt.get_unverified_header(token)
    body = pyjwt.decode(token, options={"verify_signature": False})

    assert header["typ"] == JWT_TYPE
    assert isinstance(header["kid"], str) and header["kid"]
    assert "kid" not in body
    assert body["dom"] == JWT_DOMAIN
    verified = _verify_login(jwt_service, token, token_type)
    assert verified.sub == "wallet_header"
    assert verified.type == token_type


@pytest.mark.parametrize("token_type", ["access", "refresh"])
def test_login_token_rejects_a_receipt_domain_claim(jwt_service, token_type):
    """The same login key must not accept a token labeled as a receipt."""
    private_key, signing_key_id = jwt_service._load_keys()
    claims = _login_claims(token_type)
    claims["dom"] = "receipt"
    token = pyjwt.encode(
        claims,
        private_key,
        algorithm=JWT_ALGORITHM,
        headers={"kid": signing_key_id, "typ": JWT_TYPE},
    )

    with pytest.raises(JWTError, match="token_domain_mismatch"):
        _verify_login(jwt_service, token, token_type)


def test_login_token_rejects_a_generic_jwt_type(jwt_service):
    """A normal JWT type is not the login domain, even with a valid signature."""
    private_key, signing_key_id = jwt_service._load_keys()
    token = pyjwt.encode(
        _login_claims("access"),
        private_key,
        algorithm=JWT_ALGORITHM,
        headers={"kid": signing_key_id, "typ": "JWT"},
    )

    with pytest.raises(JWTError, match="token_domain_mismatch"):
        jwt_service.verify_access_token(token)


def test_login_token_rejects_a_mismatched_header_kid(jwt_service):
    """The header key id has to name the login key that signed the token."""
    private_key, signing_key_id = jwt_service._load_keys()
    token = pyjwt.encode(
        _login_claims("access"),
        private_key,
        algorithm=JWT_ALGORITHM,
        headers={"kid": signing_key_id + "-other", "typ": JWT_TYPE},
    )

    with pytest.raises(JWTError, match="signing_key_mismatch"):
        jwt_service.verify_access_token(token)
