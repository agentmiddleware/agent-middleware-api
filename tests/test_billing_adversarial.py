"""Adversarial regression tests for billing charges and Stripe top-up failures.

Covers two breaks found by break-it testing against local test setups only
(test doubles throughout, no live Stripe or production charging):

1. Sub-precision ("dust") charges rounded to zero on write yet answered 200,
   metering service for free and writing zero-value debit rows.
2. The Stripe ``payment_intent.payment_failed`` handler crashed with
   KeyError, AttributeError, or TypeError on malformed payloads, turning the
   webhook into a 500 that Stripe retries forever while the failure alert
   never goes out.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.stripe_integration import StripeIntegration


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


async def _make_sponsor(client, api_headers, credits: float) -> dict:
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"Adversarial {uuid.uuid4().hex[:8]}",
            "email": f"{uuid.uuid4().hex[:8]}@adversarial.test",
            "initial_credits": credits,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _balance(wallet_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _debits(wallet_id: str) -> list:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(LedgerEntryModel).where(
                LedgerEntryModel.wallet_id == wallet_id,
                LedgerEntryModel.action == "debit",
            )
        )
        return list(result.scalars().all())


@pytest.mark.anyio
async def test_dust_charge_refused_at_http(client, api_headers, clean_database):
    """A charge below the ledger's stored precision must not answer 200."""
    wallet = await _make_sponsor(client, api_headers, 10.0)
    wallet_id = wallet["wallet_id"]

    resp = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=platform_fee"
        f"&units=1e-9&request_path=POST+/dust",
        headers=api_headers,
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_charge"
    assert await _balance(wallet_id) == Decimal("10")
    assert await _debits(wallet_id) == []


@pytest.mark.anyio
async def test_dust_charge_refused_at_engine(clean_database):
    """The engine floor holds for SDK and governed callers, not just HTTP."""
    wallet = await get_agent_money().create_sponsor_wallet(
        sponsor_name=f"Dust Engine {uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@adversarial.test",
        initial_credits=Decimal("10"),
        require_kyc=False,
    )

    with pytest.raises(ValueError, match="below the minimum"):
        await get_agent_money().charge(
            wallet_id=wallet.wallet_id,
            service_category=ServiceCategory.PLATFORM_FEE,
            units=Decimal("1e-9"),
        )

    assert await _balance(wallet.wallet_id) == Decimal("10")
    assert await _debits(wallet.wallet_id) == []


@pytest.mark.anyio
async def test_minimum_charge_boundary_still_accepted(
    client, api_headers, clean_database
):
    """Exactly one atomic unit (1e-8) still debits; dry runs still estimate."""
    wallet = await _make_sponsor(client, api_headers, 10.0)
    wallet_id = wallet["wallet_id"]

    resp = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=platform_fee"
        f"&units=1e-7&request_path=POST+/boundary",
        headers=api_headers,
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["amount_exact"]) == Decimal("-1E-8")
    assert await _balance(wallet_id) == Decimal("10") - Decimal("0.00000001")

    dry = await get_agent_money().charge(
        wallet_id=wallet_id,
        service_category=ServiceCategory.PLATFORM_FEE,
        units=Decimal("1e-9"),
        dry_run=True,
    )
    assert dry.would_succeed is True


@pytest.mark.anyio
async def test_payment_failed_without_metadata_does_not_raise(clean_database):
    """A payment_failed event with no metadata must be logged, not crash."""
    integration = StripeIntegration()
    with patch("app.services.notifications.get_notification_service") as mock_service:
        mock_service.return_value.send_payment_failed_alert = AsyncMock()
        await integration._handle_payment_failed({"id": "pi_missing_meta"})
        mock_service.return_value.send_payment_failed_alert.assert_not_called()


@pytest.mark.anyio
async def test_payment_failed_with_null_error_sends_unknown_error(
    clean_database,
):
    """A null last_payment_error must still alert with a default message."""
    integration = StripeIntegration()
    with patch("app.services.notifications.get_notification_service") as mock_service:
        mock_service.return_value.send_payment_failed_alert = AsyncMock()
        await integration._handle_payment_failed(
            {
                "id": "pi_null_error",
                "metadata": {"wallet_id": "spn-test"},
                "last_payment_error": None,
            }
        )
        mock_service.return_value.send_payment_failed_alert.assert_called_once()
        kwargs = mock_service.return_value.send_payment_failed_alert.call_args.kwargs
        assert kwargs["error_message"] == "Unknown error"
        assert kwargs["wallet_id"] == "spn-test"
        assert kwargs["payment_intent_id"] == "pi_null_error"


@pytest.mark.anyio
async def test_payment_failed_with_non_object_payload_does_not_raise(
    clean_database,
):
    integration = StripeIntegration()
    with patch("app.services.notifications.get_notification_service") as mock_service:
        mock_service.return_value.send_payment_failed_alert = AsyncMock()
        await integration._handle_payment_failed(None)
        mock_service.return_value.send_payment_failed_alert.assert_not_called()


@pytest.mark.anyio
async def test_webhook_payment_failed_malformed_answers_200(client, clean_database):
    """End to end: a malformed failure event is received, never a 500."""
    event = {
        "id": "evt_malformed",
        "type": "payment_intent.payment_failed",
        "data": {"object": {"id": "pi_malformed"}},
    }
    with patch(
        "app.services.stripe_integration.stripe.Webhook.construct_event",
        return_value=event,
    ):
        resp = await client.post(
            "/v1/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "received"}


@pytest.mark.anyio
async def test_topup_prepare_stripe_failure_leaves_no_trace(
    client, api_headers, clean_database
):
    """A Stripe outage mid-prepare must fail closed with nothing minted."""
    wallet = await _make_sponsor(client, api_headers, 5.0)
    wallet_id = wallet["wallet_id"]

    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create",
        side_effect=Exception("stripe is down"),
    ):
        resp = await client.post(
            f"/v1/billing/top-up/prepare?wallet_id={wallet_id}&amount_fiat=50.0",
            headers=api_headers,
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "topup_prepare_error"
    assert await _balance(wallet_id) == Decimal("5")
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(LedgerEntryModel).where(
                LedgerEntryModel.wallet_id == wallet_id,
            )
        )
        entries = list(result.scalars().all())
    assert len(entries) == 1
    assert entries[0].action == "credit"
