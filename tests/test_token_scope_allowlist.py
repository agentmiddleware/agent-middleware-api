"""Login tokens must not carry caller-invented scope names.

POST /v1/auth/token used to mint whatever scope strings the caller asked
for. No route checks scopes today, but the first scope-checked route would
have trusted those self-minted names, so requested scopes are intersected
with the allowlist at mint time (and re-applied at refresh, which contains
refresh tokens minted before the fix).
"""

import base64

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import AuthContext, get_auth_context
from app.core.config import get_settings
from app.core.jwt import get_jwt_service
from app.core.scopes import ALLOWED_TOKEN_SCOPES, require_scope
from app.db.database import get_session_factory
from app.db.models import RefreshTokenModel, WalletModel
from app.routers import auth
from app.routers.auth import _exp_to_datetime
from app.services.api_key_service import get_api_key_service


@pytest.fixture
async def client(clean_database, monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(bytes(range(32))).decode(),
    )
    app = FastAPI()
    app.include_router(auth.router)  # Explicit dormant-surface opt-in.

    @app.get("/guarded-billing")
    @require_scope("billing:charge")
    async def guarded_billing(auth: AuthContext = Depends(get_auth_context)):
        return {"allowed": True}

    # "admin:all" is deliberately NOT in ALLOWED_TOKEN_SCOPES: it stands in
    # for any future scope-checked route trusting a name the service mints.
    assert "admin:all" not in ALLOWED_TOKEN_SCOPES

    @app.get("/guarded-admin")
    @require_scope("admin:all")
    async def guarded_admin(auth: AuthContext = Depends(get_auth_context)):
        return {"allowed": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def seed(wallet_id):
    async with get_session_factory()() as session:
        session.add(WalletModel(wallet_id=wallet_id, wallet_type="agent"))
        await session.commit()
    return await get_api_key_service().create_key(wallet_id)


async def test_exchange_drops_requested_scopes_outside_allowlist(client):
    key = await seed("qa_scope_allowlist")
    response = await client.post(
        "/v1/auth/token",
        json={
            "api_key": key["api_key"],
            "scopes": ["billing:charge", "admin:all"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "billing:charge"
    payload = get_jwt_service().verify_access_token(body["access_token"])
    assert payload.scopes == ["billing:charge"]
    bearer = {"Authorization": "Bearer " + body["access_token"]}
    assert (await client.get("/guarded-billing", headers=bearer)).status_code == 200
    assert (await client.get("/guarded-admin", headers=bearer)).status_code == 403


async def test_exchange_with_only_unknown_scopes_mints_empty_scope_token(client):
    key = await seed("qa_scope_unknown_only")
    response = await client.post(
        "/v1/auth/token",
        json={"api_key": key["api_key"], "scopes": ["admin:all"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == ""
    payload = get_jwt_service().verify_access_token(body["access_token"])
    assert payload.scopes == []
    bearer = {"Authorization": "Bearer " + body["access_token"]}
    assert (await client.get("/guarded-billing", headers=bearer)).status_code == 403
    assert (await client.get("/guarded-admin", headers=bearer)).status_code == 403


async def test_refresh_reapplies_allowlist_to_legacy_tokens(client):
    """A refresh token minted before filtering cannot reintroduce names."""
    key = await seed("qa_scope_refresh")
    jwt_svc = get_jwt_service()
    legacy_refresh = jwt_svc.create_refresh_token(
        wallet_id="qa_scope_refresh",
        scopes=["billing:charge", "admin:all"],
    )
    legacy_payload = jwt_svc.verify_refresh_token(legacy_refresh)
    async with get_session_factory()() as session:
        session.add(
            RefreshTokenModel(
                jti=legacy_payload.jti,
                wallet_id="qa_scope_refresh",
                key_id=key["key_id"],
                expires_at=_exp_to_datetime(legacy_payload.exp),
            )
        )
        await session.commit()

    response = await client.post(
        "/v1/auth/refresh", json={"refresh_token": legacy_refresh}
    )
    assert response.status_code == 200
    payload = jwt_svc.verify_access_token(response.json()["access_token"])
    assert payload.scopes == ["billing:charge"]
