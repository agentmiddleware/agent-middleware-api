"""
Tests for API Key Rotation Service.
Validates key creation, rotation, revocation, and emergency procedures.
"""

import pytest
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.database import get_session_factory
from app.db.models import APIKeyModel

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


@pytest.fixture
async def sponsor_wallet(client, api_headers):
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "API Key Test Corp",
            "email": "apikey@test.com",
            "initial_credits": 10000.0,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.anyio
async def test_create_api_key(client, api_headers, sponsor_wallet):
    """Test creating a new API key."""
    resp = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "key_name": "test_key",
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["wallet_id"] == sponsor_wallet["wallet_id"]
    assert data["api_key"].startswith("b2a_")
    assert len(data["api_key"]) > 20
    assert data["status"] == "active"


@pytest.mark.anyio
async def test_create_api_key_with_expiration(client, api_headers, sponsor_wallet):
    """Test creating an API key with expiration."""
    resp = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "key_name": "temp_key",
            "expires_in_days": 30,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expires_at"] is not None


@pytest.mark.anyio
async def test_create_api_key_wallet_not_found(client, api_headers):
    """Test creating a key for a non-existent wallet."""
    resp = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": "nonexistent-wallet",
            "key_name": "test_key",
        },
        headers=api_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_api_keys(client, api_headers, sponsor_wallet):
    """Test listing API keys for a wallet."""
    await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )

    resp = await client.get(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}",
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["wallet_id"] == sponsor_wallet["wallet_id"]
    assert len(data["keys"]) == 1
    assert data["total_active"] == 1


@pytest.mark.anyio
async def test_rotate_api_key(client, api_headers, sponsor_wallet):
    """Test rotating an API key."""
    create_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    old_key = create_resp.json()

    resp = await client.post(
        "/v1/api-keys/rotate",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "key_id": old_key["key_id"],
            "revoke_old": True,
            "reason": "test_rotation",
        },
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["old_key_id"] == old_key["key_id"]
    assert data["new_key"] is not None
    assert data["new_key"]["api_key"] != old_key["api_key"]
    assert data["rotation_type"] == "manual"


@pytest.mark.anyio
async def test_rotate_api_key_without_revoke(client, api_headers, sponsor_wallet):
    """Test rotating a key without revoking the old one."""
    create_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    old_key = create_resp.json()

    resp = await client.post(
        "/v1/api-keys/rotate",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "key_id": old_key["key_id"],
            "revoke_old": False,
        },
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["revoked_keys"] == []

    list_resp = await client.get(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}",
        headers=api_headers,
    )
    assert list_resp.json()["total_active"] == 2


@pytest.mark.anyio
async def test_revoke_api_key(client, api_headers, sponsor_wallet):
    """Test revoking an API key."""
    create_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    key = create_resp.json()

    resp = await client.delete(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}/{key['key_id']}",
        params={"reason": "test_revocation"},
        headers=api_headers,
    )
    assert resp.status_code == 204

    list_resp = await client.get(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}",
        headers=api_headers,
    )
    assert list_resp.json()["total_active"] == 0
    assert list_resp.json()["total_revoked"] == 1


@pytest.mark.anyio
async def test_revoke_api_key_not_found(client, api_headers, sponsor_wallet):
    """Test revoking a non-existent API key."""
    resp = await client.delete(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}/nonexistent-key",
        headers=api_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_emergency_revoke(client, api_headers, sponsor_wallet):
    """Test emergency key revocation."""
    await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )

    resp = await client.post(
        "/v1/api-keys/emergency-revoke",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "reason": "security_incident",
            "create_new_key": True,
        },
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["revoked_keys"]) == 2
    assert data["new_key"] is not None
    assert data["new_key"]["api_key"].startswith("b2a_")


@pytest.mark.anyio
async def test_get_rotation_logs(client, api_headers, sponsor_wallet):
    """Test getting rotation audit logs."""
    create_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    key = create_resp.json()

    await client.post(
        "/v1/api-keys/rotate",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "key_id": key["key_id"],
            "revoke_old": True,
            "reason": "test_rotation",
        },
        headers=api_headers,
    )

    resp = await client.get(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}/logs",
        headers=api_headers,
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert logs[0]["wallet_id"] == sponsor_wallet["wallet_id"]


@pytest.mark.anyio
async def test_api_key_response_includes_warning(client, api_headers, sponsor_wallet):
    """Test that key creation response includes security warning."""
    resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "warning" in data
    assert "Store this key securely" in data["warning"]


@pytest.mark.anyio
async def test_db_created_key_authenticates_and_is_wallet_scoped(
    client, api_headers, sponsor_wallet
):
    """DB-created keys authenticate but only for their issuing wallet."""
    other_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Other Corp",
            "email": "other@test.com",
            "initial_credits": 1000.0,
        },
        headers=api_headers,
    )
    other_wallet = other_resp.json()

    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    db_key = key_resp.json()["api_key"]
    db_headers = {"X-API-Key": db_key}

    own_resp = await client.get(
        f"/v1/billing/wallets/{sponsor_wallet['wallet_id']}",
        headers=db_headers,
    )
    assert own_resp.status_code == 200

    other_read = await client.get(
        f"/v1/billing/wallets/{other_wallet['wallet_id']}",
        headers=db_headers,
    )
    assert other_read.status_code == 403

    other_keys = await client.get(
        f"/v1/api-keys/{other_wallet['wallet_id']}",
        headers=db_headers,
    )
    assert other_keys.status_code == 403

    own_key_create = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"], "key_name": "self_managed"},
        headers=db_headers,
    )
    assert own_key_create.status_code == 201


@pytest.mark.anyio
async def test_revoked_db_key_cannot_authenticate(client, api_headers, sponsor_wallet):
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    key = key_resp.json()

    revoke_resp = await client.delete(
        f"/v1/api-keys/{sponsor_wallet['wallet_id']}/{key['key_id']}",
        headers=api_headers,
    )
    assert revoke_resp.status_code == 204

    resp = await client.get(
        "/v1/billing/pricing",
        headers={"X-API-Key": key["api_key"]},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_expired_db_key_cannot_authenticate(client, api_headers, sponsor_wallet):
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": sponsor_wallet["wallet_id"]},
        headers=api_headers,
    )
    key = key_resp.json()

    factory = get_session_factory()
    async with factory() as session:
        db_key = await session.get(APIKeyModel, key["key_id"])
        db_key.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await session.commit()

    resp = await client.get(
        "/v1/billing/pricing",
        headers={"X-API-Key": key["api_key"]},
    )
    assert resp.status_code == 403
