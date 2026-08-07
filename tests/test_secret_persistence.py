"""Regression coverage for raw API-key persistence boundaries."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import ServiceRegistryModel, WalletModel
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


def test_wallet_and_service_tables_have_no_raw_owner_key_columns():
    """Live API credentials must never be persisted as ownership metadata."""
    assert "owner_key" not in WalletModel.__table__.columns
    assert "owner_key" not in ServiceRegistryModel.__table__.columns


@pytest.mark.anyio
async def test_wallet_scoped_key_registers_service_by_wallet_identity(
    client,
    api_headers,
    clean_database,
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Service Owner",
            "email": "service-owner@example.com",
            "initial_credits": 100,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201
    wallet_id = sponsor.json()["wallet_id"]

    key = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "service-registration"},
        headers=api_headers,
    )
    assert key.status_code == 201

    response = await client.post(
        "/v1/billing/services",
        json={
            "name": "Wallet-owned service",
            "description": "Regression fixture",
            "category": "agent_comms",
            "credits_per_unit": 1,
            "owner_wallet_id": "spn-attacker-selected-owner",
        },
        headers={"X-API-Key": key.json()["api_key"]},
    )

    assert response.status_code == 201, response.text
    assert response.json()["owner_wallet_id"] == wallet_id

    factory = get_session_factory()
    async with factory() as session:
        service = await session.get(
            ServiceRegistryModel,
            response.json()["service_id"],
        )
    assert service is not None
    assert service.owner_wallet_id == wallet_id


@pytest.mark.anyio
async def test_unauthenticated_service_registration_is_rejected(
    client,
    clean_database,
):
    response = await client.post(
        "/v1/billing/services",
        json={
            "name": "Anonymous service",
            "category": "agent_comms",
            "credits_per_unit": 1,
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "missing_credentials"


@pytest.mark.anyio
async def test_bootstrap_key_cannot_register_unowned_service(
    client,
    api_headers,
    clean_database,
):
    response = await client.post(
        "/v1/billing/services",
        json={
            "name": "Unowned service",
            "category": "agent_comms",
            "credits_per_unit": 1,
        },
        headers=api_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "wallet_identity_required"
