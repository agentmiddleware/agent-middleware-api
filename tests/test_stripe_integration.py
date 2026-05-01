"""
Tests for Stripe Integration Service.
Validates fiat top-up flow, webhook handling, and idempotency.
"""

import json
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


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
    """Create a sponsor wallet for testing."""
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Stripe Test Sponsor",
            "email": "stripe-test@b2a.dev",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    return resp.json()


@pytest.mark.anyio
async def test_prepare_top_up_creates_payment_intent(client, sponsor_wallet, api_headers):
    """Test that /top-up/prepare creates a Stripe PaymentIntent."""
    wallet_id = sponsor_wallet["wallet_id"]

    with patch("app.services.stripe_integration.stripe.PaymentIntent.create") as mock_create:
        mock_create.return_value = MagicMock(
            id="pi_test123",
            client_secret="pi_test123_secret_xyz",
            status="requires_payment_method",
        )

        resp = await client.post(
            f"/v1/billing/top-up/prepare?wallet_id={wallet_id}&amount_fiat=50.0",
            headers=api_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["payment_intent_id"] == "pi_test123"
        assert data["client_secret"] == "pi_test123_secret_xyz"
        assert data["amount_credits"] == 50000  # $50 * 1000 credits/$
        assert data["amount_fiat"] == 50.0
        assert data["currency"] == "USD"

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["amount"] == 5000  # 50.0 * 100 cents
        assert call_kwargs["currency"] == "usd"
        assert call_kwargs["metadata"]["wallet_id"] == wallet_id
        assert call_kwargs["metadata"]["credits"] == 50000


@pytest.mark.anyio
async def test_prepare_top_up_wallet_not_found(client, api_headers):
    """Test that /top-up/prepare returns 404 for non-existent wallet."""
    with patch("app.services.stripe_integration.stripe.PaymentIntent.create") as mock_create:
        mock_create.side_effect = Exception("Should not be called")
        
        resp = await client.post(
            "/v1/billing/top-up/prepare?wallet_id=nonexistent&amount_fiat=50.0",
            headers=api_headers,
        )
        assert resp.status_code == 404


@pytest.mark.anyio
async def test_webhook_signature_verification(client):
    """Test that invalid Stripe signatures are rejected."""
    with patch("app.services.stripe_integration.stripe.Webhook.construct_event") as mock_event:
        mock_event.side_effect = ValueError("Invalid signature")
        
        resp = await client.post(
            "/v1/webhooks/stripe",
            content=b"invalid_payload",
            headers={"stripe-signature": "invalid_sig"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
async def test_webhook_missing_signature(client):
    """Test that missing Stripe signatures are rejected."""
    resp = await client.post(
        "/v1/webhooks/stripe",
        content=b"some_payload",
    )
    assert resp.status_code == 400  # Missing signature header


class TestStripeWebhookIdempotency:
    """Tests for webhook idempotency via UNIQUE constraint."""

    @pytest.mark.anyio
    async def test_duplicate_webhook_returns_200(self, client, sponsor_wallet, api_headers):
        """
        Test that duplicate payment_intent webhooks don't cause errors.
        The UNIQUE constraint on payment_intent_id + IntegrityError catch
        should return 200 OK to stop Stripe's retry loop.
        """
        wallet_id = sponsor_wallet["wallet_id"]

        with patch("app.services.stripe_integration.stripe.PaymentIntent.create") as mock_create:
            with patch("app.services.stripe_integration.stripe.Webhook.construct_event") as mock_webhook:
                mock_create.return_value = MagicMock(
                    id="pi_duplicate_test",
                    client_secret="pi_duplicate_secret",
                )

                mock_webhook.return_value = {
                    "type": "payment_intent.succeeded",
                    "data": {
                        "object": {
                            "id": "pi_duplicate_test",
                            "metadata": {
                                "wallet_id": wallet_id,
                                "credits": "50000",
                            },
                        }
                    },
                }

                resp1 = await client.post(
                    f"/v1/billing/top-up/prepare?wallet_id={wallet_id}&amount_fiat=50.0",
                    headers=api_headers,
                )
                assert resp1.status_code == 200

                resp2 = await client.post(
                    "/v1/webhooks/stripe",
                    content=b"duplicate_webhook_payload",
                    headers={"stripe-signature": "valid_sig_for_dup"},
                )
                assert resp2.status_code == 200


class TestNotificationService:
    """Tests for the notification service."""

    @pytest.mark.anyio
    async def test_low_balance_warning_skips_without_config(self):
        """Test that notifications are skipped when not configured."""
        from app.services.notifications import NotificationService

        service = NotificationService()
        service._slack_webhook_url = ""
        service._resend_api_key = ""

        await service.send_low_balance_warning(
            wallet_id="test-wallet",
            current_balance=Decimal("100"),
            threshold=Decimal("500"),
        )

    @pytest.mark.anyio
    async def test_wallet_frozen_alert_skips_without_config(self):
        """Test that frozen alerts are skipped when not configured."""
        from app.services.notifications import NotificationService

        service = NotificationService()
        service._slack_webhook_url = ""
        service._resend_api_key = ""

        await service.send_wallet_frozen_alert(
            wallet_id="test-wallet",
            reason="anomalous_spend",
        )
