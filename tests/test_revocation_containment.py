"""Revoking an API key must also kill the JWTs derived from it.

A JWT is derived authority: it exists only because an API key was presented at
/v1/auth/token. Before these fixes, revocation did not contain a compromise —
POST /v1/auth/refresh checked only the token signature and the stored revoked
flag, so an attacker holding a refresh token minted from a stolen key kept
issuing access tokens for the refresh lifetime after the key was revoked.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.jwt import JWT_AUTHORITY_SCOPES, get_jwt_service
from app.db.database import get_session_factory
from app.db.models import RefreshTokenModel
from app.main import app
from app.routers.auth import _exp_to_datetime
from app.services.api_key_service import get_api_key_service
from tests.test_trust_helpers import provision_agent_wallet

# 32 raw bytes, strict base64 — same non-secret test material CI uses.
TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", TEST_SIGNING_KEY)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _mint_tokens(client, api_key: str) -> dict:
    resp = await client.post("/v1/auth/token", json={"api_key": api_key})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scopes",
    [
        [],
        ["tool:invoke"],
        ["billing:charge"],
        ["billing:read"],
        [*JWT_AUTHORITY_SCOPES, "api-keys:manage"],
        ["billing:charge", "billing:charge", "tool:invoke"],
    ],
)
async def test_token_exchange_rejects_non_authoritative_scope_profiles(
    client,
    clean_database,
    signing_key,
    scopes,
):
    provisioned = await provision_agent_wallet(client)

    response = await client.post(
        "/v1/auth/token",
        json={
            "api_key": provisioned["agent_headers"]["X-API-Key"],
            "scopes": scopes,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "unsupported_jwt_scope_profile"


@pytest.mark.anyio
async def test_new_refresh_token_carries_key_and_authority_profile(
    client,
    clean_database,
    signing_key,
):
    provisioned = await provision_agent_wallet(client)
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])

    payload = get_jwt_service().verify_refresh_token(tokens["refresh_token"])

    assert payload.key_id == provisioned["key_id"]
    assert payload.scopes == list(JWT_AUTHORITY_SCOPES)


@pytest.mark.anyio
async def test_token_exchange_accepts_exact_authority_profile(
    client,
    clean_database,
    signing_key,
):
    provisioned = await provision_agent_wallet(client)

    response = await client.post(
        "/v1/auth/token",
        json={
            "api_key": provisioned["agent_headers"]["X-API-Key"],
            "scopes": list(reversed(JWT_AUTHORITY_SCOPES)),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == " ".join(JWT_AUTHORITY_SCOPES)


@pytest.mark.anyio
async def test_legacy_scope_less_refresh_token_fails_closed(
    client,
    clean_database,
    signing_key,
):
    provisioned = await provision_agent_wallet(client)
    legacy = get_jwt_service().create_refresh_token(
        wallet_id=provisioned["agent_wallet_id"]
    )
    payload = get_jwt_service().verify_refresh_token(legacy)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            RefreshTokenModel(
                jti=payload.jti,
                wallet_id=payload.sub,
                key_id=provisioned["key_id"],
                expires_at=_exp_to_datetime(payload.exp),
            )
        )
        await session.commit()

    response = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": legacy},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_refresh_token"


@pytest.mark.anyio
async def test_refresh_works_while_the_key_is_active(
    client, clean_database, signing_key
):
    """Control: the happy path must keep working."""
    provisioned = await provision_agent_wallet(client)
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])

    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


@pytest.mark.anyio
async def test_refresh_parent_can_create_only_one_live_child(
    client, clean_database, signing_key
):
    provisioned = await provision_agent_wallet(client)
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])
    parent = get_jwt_service().verify_refresh_token(tokens["refresh_token"])

    winner = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    loser = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert winner.status_code == 200, winner.text
    assert loser.status_code == 401
    assert loser.json()["detail"]["error"] == "revoked_refresh_token"

    child_token = winner.json()["refresh_token"]
    child = get_jwt_service().verify_refresh_token(child_token)
    assert child.key_id == provisioned["key_id"]
    assert child.scopes == list(JWT_AUTHORITY_SCOPES)

    factory = get_session_factory()
    async with factory() as session:
        records = (
            (
                await session.execute(
                    select(RefreshTokenModel).where(
                        RefreshTokenModel.wallet_id == provisioned["agent_wallet_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {record.jti for record in records} == {parent.jti, child.jti}
    assert next(record for record in records if record.jti == parent.jti).revoked
    assert not next(record for record in records if record.jti == child.jti).revoked

    redeem_child = await client.post(
        "/v1/auth/refresh", json={"refresh_token": child_token}
    )
    assert redeem_child.status_code == 200, redeem_child.text


@pytest.mark.anyio
async def test_emergency_revocation_kills_refresh_tokens(
    client, clean_database, signing_key
):
    """Emergency revocation must revoke derived refresh tokens, not just keys."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])

    result = await get_api_key_service().emergency_revocation(
        wallet_id=wallet_id,
        reason="test_incident",
        create_new_key=False,
    )
    assert result["revoked_refresh_tokens"] >= 1

    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] in (
        "revoked_refresh_token",
        "no_active_api_key",
    )


@pytest.mark.anyio
async def test_refresh_denied_once_the_wallet_has_no_active_key(
    client, clean_database, signing_key
):
    """Single-key revocation also contains: no live key, no renewal.

    Uses revoke_key (not the emergency path) so this covers the ordinary
    revocation route, which does not touch refresh tokens directly.
    """
    provisioned = await provision_agent_wallet(client)
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])

    await get_api_key_service().revoke_key(
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        reason="test_revoke",
    )

    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "no_active_api_key"


@pytest.mark.anyio
async def test_refresh_denied_once_every_key_has_expired(
    client, clean_database, signing_key
):
    """Time-expiry must contain too, not just explicit revocation.

    An expired key keeps status="active" (nothing sweeps it), so a status-only
    liveness check would let refresh outlive every credential the wallet has —
    /v1/auth/token already rejects such a key.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from app.core.time import utc_now
    from app.db.database import get_session_factory
    from app.db.models import APIKeyModel

    provisioned = await provision_agent_wallet(client)
    api_key = provisioned["agent_headers"]["X-API-Key"]
    tokens = await _mint_tokens(client, api_key)

    # Expire every key for the wallet in place, leaving status "active".
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(APIKeyModel).where(
                        APIKeyModel.wallet_id == provisioned["agent_wallet_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.expires_at = utc_now() - timedelta(minutes=5)
            session.add(row)
        await session.commit()
        assert all(r.status == "active" for r in rows)

    # The front door already rejects the expired key...
    mint = await client.post("/v1/auth/token", json={"api_key": api_key})
    assert mint.status_code == 401
    # ...so refresh must not keep issuing tokens either.
    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "no_active_api_key"


@pytest.mark.anyio
async def test_revoking_one_of_several_keys_kills_only_its_own_tokens(
    client, clean_database, signing_key
):
    """Containment is per-key, not per-wallet.

    A wallet-level liveness check is too coarse: with a sibling key still
    active, a token minted from the compromised key would stay renewable. The
    token is bound to the key that minted it, so revoking that key kills its
    chain while the sibling's chain keeps working.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]

    second = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "sibling"},
        headers={"X-API-Key": "test-key"},
    )
    assert second.status_code == 201
    sibling = second.json()

    compromised_tokens = await _mint_tokens(
        client, provisioned["agent_headers"]["X-API-Key"]
    )
    sibling_tokens = await _mint_tokens(client, sibling["api_key"])

    # Revoke only the compromised key; the sibling stays active.
    await get_api_key_service().revoke_key(
        wallet_id=wallet_id,
        key_id=provisioned["key_id"],
        reason="compromised",
    )

    denied = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": compromised_tokens["refresh_token"]},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["error"] == "no_active_api_key"

    allowed = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": sibling_tokens["refresh_token"]},
    )
    assert allowed.status_code == 200, allowed.text


@pytest.mark.anyio
async def test_rotation_carries_the_key_binding_forward(
    client, clean_database, signing_key
):
    """Refreshing must not launder a bound chain into an unbound one."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])

    rotated = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert rotated.status_code == 200
    rotated_refresh = rotated.json()["refresh_token"]
    jwt_svc = get_jwt_service()
    assert jwt_svc.verify_access_token(rotated.json()["access_token"]).scopes == list(
        JWT_AUTHORITY_SCOPES
    )
    assert jwt_svc.verify_refresh_token(rotated_refresh).scopes == list(
        JWT_AUTHORITY_SCOPES
    )

    # Revoke the originating key; a second key keeps the wallet "live", so only
    # a preserved binding can deny the rotated token.
    await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "other"},
        headers={"X-API-Key": "test-key"},
    )
    await get_api_key_service().revoke_key(
        wallet_id=wallet_id,
        key_id=provisioned["key_id"],
        reason="compromised",
    )

    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": rotated_refresh}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "no_active_api_key"


@pytest.mark.anyio
async def test_rotation_revokes_access_token_derived_from_old_key(
    client, clean_database, signing_key
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])

    rotated = await client.post(
        "/v1/api-keys/rotate",
        json={
            "wallet_id": wallet_id,
            "key_id": provisioned["key_id"],
            "revoke_old": True,
            "reason": "compromise_response",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert rotated.status_code == 200, rotated.text

    denied = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "revocation-escape"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["error"] == "no_active_api_key"

    listed = await client.get(
        f"/v1/api-keys/{wallet_id}",
        headers={"X-API-Key": "test-key"},
    )
    assert listed.status_code == 200
    assert listed.json()["total_active"] == 1
    assert listed.json()["total_revoked"] == 1


@pytest.mark.anyio
async def test_legacy_unbound_refresh_token_fails_closed(
    client, clean_database, signing_key
):
    """A pre-migration token cannot renew through a live sibling key."""
    from app.core.jwt import get_jwt_service
    from app.db.database import get_session_factory
    from app.db.models import RefreshTokenModel

    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tokens = await _mint_tokens(client, provisioned["agent_headers"]["X-API-Key"])
    payload = get_jwt_service().verify_refresh_token(tokens["refresh_token"])

    sibling = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "replacement"},
        headers={"X-API-Key": "test-key"},
    )
    assert sibling.status_code == 201

    # Recreate the only state available for rows written before migration 025.
    factory = get_session_factory()
    async with factory() as session:
        record = await session.get(RefreshTokenModel, payload.jti)
        assert record is not None
        record.key_id = None
        session.add(record)
        await session.commit()

    denied = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["error"] == "unbound_refresh_token"

    async with factory() as session:
        record = await session.get(RefreshTokenModel, payload.jti)
        assert record is not None
        assert record.revoked is True


@pytest.mark.anyio
async def test_revoked_key_cannot_mint_new_tokens(client, clean_database, signing_key):
    """The front door closes too: a revoked key cannot exchange for tokens."""
    provisioned = await provision_agent_wallet(client)
    api_key = provisioned["agent_headers"]["X-API-Key"]

    await get_api_key_service().revoke_key(
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        reason="test_revoke",
    )

    resp = await client.post("/v1/auth/token", json={"api_key": api_key})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_other_wallets_are_unaffected_by_a_revocation(
    client, clean_database, signing_key
):
    """Containment must be scoped: revoking wallet A must not break wallet B."""
    victim = await provision_agent_wallet(client)
    bystander = await provision_agent_wallet(client)
    bystander_tokens = await _mint_tokens(
        client, bystander["agent_headers"]["X-API-Key"]
    )

    await get_api_key_service().emergency_revocation(
        wallet_id=victim["agent_wallet_id"],
        reason="test_incident",
        create_new_key=False,
    )

    resp = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": bystander_tokens["refresh_token"]},
    )
    assert resp.status_code == 200, resp.text
