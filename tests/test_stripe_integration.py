"""
Tests for Stripe Integration Service.
Validates fiat top-up flow, webhook handling, and idempotency.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe
from httpx import AsyncClient, ASGITransport
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.services.stripe_integration import StripeIntegration, StripeSettlementError


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


@pytest.fixture
async def wallet_hierarchy(client, api_headers):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Stripe Hierarchy Sponsor",
            "email": "stripe-hierarchy@b2a.dev",
            "initial_credits": 1000,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201, sponsor.text
    sponsor_id = sponsor.json()["wallet_id"]

    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "stripe-agent",
            "budget_credits": 200,
        },
        headers=api_headers,
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["wallet_id"]

    child = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": agent_id,
            "child_agent_id": "stripe-child",
            "budget_credits": 50,
            "max_spend": 50,
        },
        headers=api_headers,
    )
    assert child.status_code == 201, child.text

    return {
        "sponsor": sponsor_id,
        "agent": agent_id,
        "child": child.json()["wallet_id"],
    }


def succeeded_payment_intent(
    *,
    payment_intent_id: str,
    wallet_id: str,
    amount: int = 5000,
    amount_received: int = 5000,
    currency: str = "usd",
    credits: str = "50000",
) -> dict:
    return {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_intent_id,
                "status": "succeeded",
                "amount": amount,
                "amount_received": amount_received,
                "currency": currency,
                "metadata": {
                    "wallet_id": wallet_id,
                    "credits": credits,
                },
            }
        },
    }


def refunded_charge(
    *,
    payment_intent_id: str,
    amount_refunded: int,
    amount: int = 5000,
    currency: str = "usd",
    charge_id: str = "ch_refund_test",
) -> dict:
    return {
        "payment_intent": payment_intent_id,
        "amount": amount,
        "amount_refunded": amount_refunded,
        "currency": currency,
        "id": charge_id,
    }


@pytest.mark.anyio
async def test_prepare_top_up_creates_payment_intent(
    client, sponsor_wallet, api_headers
):
    """Test that /top-up/prepare creates a Stripe PaymentIntent."""
    wallet_id = sponsor_wallet["wallet_id"]

    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
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
        assert call_kwargs["metadata"]["credits"] == "50000"


@pytest.mark.anyio
async def test_prepare_top_up_rejects_non_usd_in_api_and_service(
    client, sponsor_wallet, api_headers
):
    wallet_id = sponsor_wallet["wallet_id"]
    integration = StripeIntegration()

    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        response = await client.post(
            f"/v1/billing/top-up/prepare?wallet_id={wallet_id}"
            "&amount_fiat=50.0&currency=EUR",
            headers=api_headers,
        )
        assert response.status_code == 400

        with pytest.raises(ValueError, match="unsupported_top_up_currency"):
            await integration.create_top_up_intent(
                wallet_id=wallet_id,
                amount_fiat=Decimal("50"),
                currency="eur",
            )

    mock_create.assert_not_called()


@pytest.mark.anyio
async def test_prepare_top_up_rejects_agent_and_child_wallets(
    client, wallet_hierarchy, api_headers
):
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        for wallet_type in ("agent", "child"):
            wallet_id = wallet_hierarchy[wallet_type]
            response = await client.post(
                f"/v1/billing/top-up/prepare?wallet_id={wallet_id}&amount_fiat=1",
                headers=api_headers,
            )
            assert response.status_code == 400
            assert response.json()["detail"]["error"] == "topup_prepare_error"

    mock_create.assert_not_called()


@pytest.mark.anyio
async def test_prepare_top_up_wallet_not_found(client, api_headers):
    """Test that /top-up/prepare returns 404 for non-existent wallet."""
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        mock_create.side_effect = Exception("Should not be called")

        resp = await client.post(
            "/v1/billing/top-up/prepare?wallet_id=nonexistent&amount_fiat=50.0",
            headers=api_headers,
        )
        assert resp.status_code == 404


@pytest.mark.anyio
async def test_webhook_signature_verification(client):
    """Test that invalid Stripe signatures are rejected."""
    with (
        patch(
            "app.services.stripe_integration.stripe.Webhook.construct_event",
            side_effect=stripe.SignatureVerificationError(
                "Invalid signature", "invalid_sig"
            ),
        ),
        patch.object(
            StripeIntegration, "_mint_credits", new_callable=AsyncMock
        ) as mock_mint,
    ):
        resp = await client.post(
            "/v1/webhooks/stripe",
            content=b"invalid_payload",
            headers={"stripe-signature": "invalid_sig"},
        )

    assert resp.status_code == 400
    mock_mint.assert_not_awaited()


@pytest.mark.anyio
async def test_webhook_missing_signature(client):
    """Test that missing Stripe signatures are rejected."""
    resp = await client.post(
        "/v1/webhooks/stripe",
        content=b"some_payload",
    )
    assert resp.status_code == 400  # Missing signature header


@pytest.mark.anyio
async def test_webhook_rejects_metadata_credit_inflation(
    client, sponsor_wallet, api_headers
):
    """A signed Stripe event cannot mint more than its settled USD amount."""
    wallet_id = sponsor_wallet["wallet_id"]
    forged_event = succeeded_payment_intent(
        payment_intent_id="pi_forged_credits",
        wallet_id=wallet_id,
        credits="50000000",
    )

    with patch(
        "app.services.stripe_integration.stripe.Webhook.construct_event",
        return_value=forged_event,
    ):
        response = await client.post(
            "/v1/webhooks/stripe",
            content=b"signed_but_forged_metadata",
            headers={"stripe-signature": "valid_signature"},
        )

    assert response.status_code == 400
    wallet = await client.get(f"/v1/billing/wallets/{wallet_id}", headers=api_headers)
    assert wallet.json()["balance"] == 0.0


@pytest.mark.anyio
async def test_webhook_rejects_invalid_settlement_fields_without_minting(
    client, sponsor_wallet, api_headers
):
    wallet_id = sponsor_wallet["wallet_id"]
    invalid_events = [
        succeeded_payment_intent(
            payment_intent_id="pi_non_usd",
            wallet_id=wallet_id,
            currency="eur",
        ),
        succeeded_payment_intent(
            payment_intent_id="pi_amount_mismatch",
            wallet_id=wallet_id,
            amount_received=1000,
            credits="10000",
        ),
        succeeded_payment_intent(
            payment_intent_id="pi_credit_metadata_missing",
            wallet_id=wallet_id,
            credits="",
        ),
    ]

    with patch(
        "app.services.stripe_integration.stripe.Webhook.construct_event",
        side_effect=invalid_events,
    ):
        for event in invalid_events:
            response = await client.post(
                "/v1/webhooks/stripe",
                content=event["data"]["object"]["id"].encode(),
                headers={"stripe-signature": "valid_signature"},
            )
            assert response.status_code == 400

    wallet = await client.get(f"/v1/billing/wallets/{wallet_id}", headers=api_headers)
    assert wallet.json()["balance"] == 0.0


@pytest.mark.anyio
async def test_webhook_rejects_agent_and_child_wallets(
    client, wallet_hierarchy, api_headers
):
    events = [
        succeeded_payment_intent(
            payment_intent_id=f"pi_{wallet_type}_wallet",
            wallet_id=wallet_hierarchy[wallet_type],
            amount=100,
            amount_received=100,
            credits="1000",
        )
        for wallet_type in ("agent", "child")
    ]
    starting_balances = {}
    for wallet_type in ("agent", "child"):
        wallet_id = wallet_hierarchy[wallet_type]
        wallet = await client.get(
            f"/v1/billing/wallets/{wallet_id}", headers=api_headers
        )
        starting_balances[wallet_id] = wallet.json()["balance"]

    with patch(
        "app.services.stripe_integration.stripe.Webhook.construct_event",
        side_effect=events,
    ):
        for event in events:
            response = await client.post(
                "/v1/webhooks/stripe",
                content=event["data"]["object"]["id"].encode(),
                headers={"stripe-signature": "valid_signature"},
            )
            assert response.status_code == 400

    for wallet_id, starting_balance in starting_balances.items():
        wallet = await client.get(
            f"/v1/billing/wallets/{wallet_id}", headers=api_headers
        )
        assert wallet.json()["balance"] == starting_balance


class TestStripeWebhookIdempotency:
    """Tests for webhook idempotency via UNIQUE constraint."""

    def test_only_stripe_event_unique_errors_are_idempotent_for_refunds(self):
        """Only the refund event-id unique constraint is swallowed."""
        duplicate = IntegrityError(
            "insert",
            {},
            Exception("UNIQUE constraint failed: ledger_entries.stripe_event_id"),
        )
        foreign_key = IntegrityError(
            "insert",
            {},
            Exception("FOREIGN KEY constraint failed"),
        )
        assert StripeIntegration._is_duplicate_stripe_event_error(duplicate) is True
        assert StripeIntegration._is_duplicate_stripe_event_error(foreign_key) is False

    @pytest.mark.anyio
    async def test_redelivered_refund_debits_only_once(
        self, client, sponsor_wallet, api_headers
    ):
        """A redelivered charge.refunded event (same event id) must not debit
        the wallet twice."""
        from app.services.stripe_integration import get_stripe_integration
        from app.core.dependencies import get_agent_money

        wallet_id = sponsor_wallet["wallet_id"]
        integration = get_stripe_integration()
        money = get_agent_money()

        # Mint 50000 credits so there is a payment-intent ledger entry to refund.
        await integration._mint_credits(
            wallet_id=wallet_id,
            amount=Decimal("50000"),
            payment_intent_id="pi_refund_test",
            description="topup",
        )
        assert (await money.get_wallet(wallet_id)).balance == Decimal("50000")

        refund_charge = refunded_charge(
            payment_intent_id="pi_refund_test",
            amount_refunded=5000,
        )
        # First delivery debits.
        await integration._handle_refund(refund_charge, "evt_refund_1")
        assert (await money.get_wallet(wallet_id)).balance == Decimal("0")

        # Redelivery of the SAME event is a no-op, not a second debit.
        await integration._handle_refund(refund_charge, "evt_refund_1")
        assert (await money.get_wallet(wallet_id)).balance == Decimal("0")

        ledger = await money.get_ledger(wallet_id, 50)
        refunds = [e for e in ledger if e.action == "refund"]
        assert len(refunds) == 1

    @pytest.mark.anyio
    async def test_chargeback_past_spent_credits_freezes_and_alerts(
        self, client, sponsor_wallet, api_headers
    ):
        """A refund for credits already spent must not pass silently.

        The deficit stays in the ledger (clamping to zero would discard a real
        loss), but the wallet is frozen — which, with wallet.status now
        authoritative, blocks further charge/transfer/child-spawn — and a
        critical alert is raised for human review.
        """
        from app.services.stripe_integration import get_stripe_integration
        from app.core.dependencies import get_agent_money
        from app.db.database import get_session_factory
        from app.db.models import BillingAlertModel
        from sqlalchemy import select

        wallet_id = sponsor_wallet["wallet_id"]
        integration = get_stripe_integration()
        money = get_agent_money()

        await integration._mint_credits(
            wallet_id=wallet_id,
            amount=Decimal("50000"),
            payment_intent_id="pi_chargeback_test",
            description="topup",
        )
        # Simulate the agent having spent most of it before the chargeback.
        await money.transfer(
            from_wallet_id=wallet_id,
            to_wallet_id=(
                await client.post(
                    "/v1/billing/wallets/sponsor",
                    json={
                        "sponsor_name": "Sink",
                        "email": "sink@b2a.dev",
                        "initial_credits": 0,
                    },
                    headers=api_headers,
                )
            ).json()["wallet_id"],
            amount=Decimal("40000"),
            description="spent",
        )
        assert (await money.get_wallet(wallet_id)).balance == Decimal("10000")

        # Full chargeback of the original 50000-credit top-up.
        await integration._handle_refund(
            {
                "payment_intent": "pi_chargeback_test",
                "amount": 5000,
                "id": "ch_chargeback_test",
            },
            "evt_chargeback_1",
        )

        wallet = await money.get_wallet(wallet_id)
        # Ledger keeps the truth: the deficit is real and recorded.
        assert wallet.balance == Decimal("-40000")
        # ...but the wallet is contained and surfaced.
        assert wallet.status.value == "frozen"

        factory = get_session_factory()
        async with factory() as session:
            alerts = (
                await session.execute(
                    select(BillingAlertModel).where(
                        BillingAlertModel.wallet_id == wallet_id
                    )
                )
            ).scalars().all()
        assert any(a.severity == "critical" for a in alerts)

    def test_only_payment_intent_unique_errors_are_idempotent(self):
        """Non-idempotency integrity errors must not be swallowed."""
        duplicate = IntegrityError(
            "insert",
            {},
            Exception("UNIQUE constraint failed: ledger_entries.payment_intent_id"),
        )
        foreign_key = IntegrityError(
            "insert",
            {},
            Exception("FOREIGN KEY constraint failed"),
        )

        assert StripeIntegration._is_duplicate_payment_intent_error(duplicate) is True
        assert (
            StripeIntegration._is_duplicate_payment_intent_error(foreign_key) is False
        )

    @pytest.mark.anyio
    async def test_duplicate_webhook_returns_200(
        self, client, sponsor_wallet, api_headers
    ):
        """
        Test that duplicate payment_intent webhooks don't cause errors.
        The UNIQUE constraint on payment_intent_id + IntegrityError catch
        should return 200 OK to stop Stripe's retry loop.
        """
        wallet_id = sponsor_wallet["wallet_id"]

        with patch(
            "app.services.stripe_integration.stripe.PaymentIntent.create"
        ) as mock_create:
            with patch(
                "app.services.stripe_integration.stripe.Webhook.construct_event"
            ) as mock_webhook:
                mock_create.return_value = MagicMock(
                    id="pi_duplicate_test",
                    client_secret="pi_duplicate_secret",
                )

                mock_webhook.return_value = succeeded_payment_intent(
                    payment_intent_id="pi_duplicate_test",
                    wallet_id=wallet_id,
                )

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

                wallet = await client.get(
                    f"/v1/billing/wallets/{wallet_id}", headers=api_headers
                )
                assert wallet.json()["balance"] == 50000.0

                # Stripe may redeliver the same verified event. The payment-intent
                # uniqueness constraint must keep the second delivery charge-neutral.
                resp3 = await client.post(
                    "/v1/webhooks/stripe",
                    content=b"duplicate_webhook_payload",
                    headers={"stripe-signature": "valid_sig_for_dup"},
                )
                assert resp3.status_code == 200

                wallet = await client.get(
                    f"/v1/billing/wallets/{wallet_id}", headers=api_headers
                )
                assert wallet.json()["balance"] == 50000.0


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
