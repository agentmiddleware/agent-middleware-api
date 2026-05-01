"""
Tests for KYC Verification (Stripe Identity).
Validates the KYC verification flow for sponsor wallets.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.models import WalletModel, KYCVerificationModel
from app.db.database import get_session_factory


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
            "sponsor_name": "KYC Test Corp",
            "email": "kyc@test.com",
            "initial_credits": 10000.0,
            "require_kyc": True,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.anyio
async def test_create_sponsor_wallet_with_kyc_required(client, api_headers):
    """Test that creating a sponsor wallet with require_kyc=True sets kyc_status to pending."""
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "KYC Required Corp",
            "email": "kyc-required@test.com",
            "initial_credits": 10000.0,
            "require_kyc": True,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["wallet_type"] == "sponsor"
    assert data["kyc_status"] == "pending"
    assert data["status"] == "pending_kyc"


@pytest.mark.anyio
async def test_create_sponsor_wallet_without_kyc(client, api_headers):
    """Test that creating a sponsor wallet without require_kyc sets kyc_status to not_required."""
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "No KYC Corp",
            "email": "no-kyc@test.com",
            "initial_credits": 10000.0,
            "require_kyc": False,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["kyc_status"] == "not_required"


@pytest.mark.anyio
async def test_get_kyc_status_pending(client, api_headers, sponsor_wallet):
    """Test getting KYC status for a pending verification."""
    resp = await client.get(
        f"/v1/kyc/status/{sponsor_wallet['wallet_id']}",
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["wallet_id"] == sponsor_wallet["wallet_id"]
    assert data["kyc_status"] == "pending"
    assert data["requires_verification"] is True
    assert "verification" in data["message"].lower()


@pytest.mark.anyio
async def test_get_kyc_status_wallet_not_found(client, api_headers):
    """Test getting KYC status for a non-existent wallet."""
    resp = await client.get(
        "/v1/kyc/status/nonexistent-wallet",
        headers=api_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_kyc_status_verified(client, api_headers):
    """Test getting KYC status for a verified wallet."""
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Verified Corp",
            "email": "verified@test.com",
            "initial_credits": 10000.0,
            "require_kyc": False,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    wallet_id = resp.json()["wallet_id"]

    resp = await client.get(
        f"/v1/kyc/status/{wallet_id}",
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kyc_status"] == "not_required"
    assert data["requires_verification"] is False


@pytest.mark.anyio
async def test_create_kyc_session_not_required(client, api_headers):
    """Test creating KYC session for a wallet that doesn't need it."""
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "No KYC Needed",
            "email": "no-kyc@test.com",
            "initial_credits": 10000.0,
            "require_kyc": False,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    wallet_id = resp.json()["wallet_id"]
    assert resp.json()["kyc_status"] == "not_required"

    resp = await client.post(
        "/v1/kyc/sessions",
        json={
            "wallet_id": wallet_id,
            "return_url": "https://example.com/callback",
        },
        headers=api_headers,
    )
    assert resp.status_code == 400
    assert "not required" in resp.json()["detail"]["message"].lower()


@pytest.mark.anyio
async def test_create_kyc_session_wallet_not_found(client, api_headers):
    """Test creating KYC session for a non-existent wallet."""
    resp = await client.post(
        "/v1/kyc/sessions",
        json={
            "wallet_id": "nonexistent-wallet",
            "return_url": "https://example.com/callback",
        },
        headers=api_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
@patch("app.services.kyc_service.stripe.identity.VerificationSession.create")
async def test_create_kyc_session_success(mock_stripe_create, client, api_headers, sponsor_wallet):
    """Test successful KYC session creation."""
    mock_session = MagicMock()
    mock_session.id = "vs_test123"
    mock_session.url = "https://verify.stripe.com/test_session"
    mock_stripe_create.return_value = mock_session

    resp = await client.post(
        "/v1/kyc/sessions",
        json={
            "wallet_id": sponsor_wallet["wallet_id"],
            "return_url": "https://example.com/callback",
            "document_type": "passport",
        },
        headers=api_headers,
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["wallet_id"] == sponsor_wallet["wallet_id"]
    assert data["session_id"] == "vs_test123"
    assert data["session_url"] == "https://verify.stripe.com/test_session"
    assert data["status"] == "pending"


@pytest.mark.anyio
async def test_get_verification_details_not_found(client, api_headers):
    """Test getting verification details for a non-existent verification."""
    resp = await client.get(
        "/v1/kyc/verifications/nonexistent-verification",
        headers=api_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_kyc_status_includes_all_fields(client, api_headers, sponsor_wallet):
    """Test that KYC status response includes all expected fields."""
    resp = await client.get(
        f"/v1/kyc/status/{sponsor_wallet['wallet_id']}",
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    required_fields = [
        "wallet_id",
        "kyc_status",
        "requires_verification",
        "message",
    ]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


@pytest.mark.anyio
async def test_wallet_response_includes_kyc_status(client, api_headers):
    """Test that wallet response includes kyc_status field."""
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "KYC Status Check",
            "email": "kyc-status@test.com",
            "initial_credits": 5000.0,
            "require_kyc": True,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "kyc_status" in data
    assert data["kyc_status"] == "pending"
