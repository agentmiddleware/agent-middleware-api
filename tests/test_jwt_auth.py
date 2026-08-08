"""Regression coverage for JWT bearer authentication."""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import AuthContext, get_auth_context
from app.core.config import get_settings
from app.core.jwt import get_jwt_service
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

    async def is_key_live(_self, _key_id: str) -> bool:
        return True

    monkeypatch.setattr(APIKeyService, "is_key_live", is_key_live)


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
    """The non-Bearer branch swallows exceptions — assert it really verifies."""
    token = jwt_service.create_access_token(
        wallet_id="wallet_raw", key_id="key_raw", scopes=[]
    )

    auth = await get_auth_context(api_key=token)

    assert auth.source == "jwt"
    assert auth.wallet_id == "wallet_raw"


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
