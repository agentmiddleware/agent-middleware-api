"""Settlement summary: minted-vs-settled reconciliation ledger half."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel
from app.main import app
from app.services.agent_money import get_agent_money
from app.services.billing_engine import _refund_payment_intent_id


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


def test_refund_intent_parsing():
    assert _refund_payment_intent_id("Refund for PaymentIntent pi_123") == "pi_123"
    assert _refund_payment_intent_id("Refund for charge ch_123") is None
    assert _refund_payment_intent_id("") is None
    assert _refund_payment_intent_id(None) is None
    assert _refund_payment_intent_id("Refund for PaymentIntent ") is None


@pytest.mark.anyio
async def test_summary_totals_a_webhook_mint(client, api_headers, clean_database):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Recon Sponsor",
            "email": "recon@example.com",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    event = {
        "type": "payment_intent.succeeded",
        "id": "evt_recon_1",
        "data": {
            "object": {
                "id": "pi_recon_1",
                "status": "succeeded",
                "amount": 5000,
                "amount_received": 5000,
                "currency": "usd",
                "metadata": {"wallet_id": wallet_id, "credits": "50000"},
            }
        },
    }
    with patch(
        "app.services.stripe_webhook_auth.stripe.Webhook.construct_event",
        return_value=event,
    ):
        resp = await client.post(
            "/v1/webhooks/stripe",
            content=b"signed",
            headers={"stripe-signature": "sig"},
        )
    assert resp.status_code == 200, resp.text

    summary = await get_agent_money().get_settlement_summary()
    assert summary["minted_count"] == 1
    assert Decimal(summary["minted_total_exact"]) == Decimal("50000")
    assert summary["refunded_count"] == 0
    assert Decimal(summary["net_minted_exact"]) == Decimal("50000")
    assert summary["mints"][0]["payment_intent_id"] == "pi_recon_1"
    assert summary["mints"][0]["wallet_id"] == wallet_id
    assert summary["orphan_refunds"] == []


@pytest.mark.anyio
async def test_summary_flags_refund_without_mint(client, api_headers, clean_database):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Orphan Sponsor",
            "email": "orphan@example.com",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    wallet_id = sponsor.json()["wallet_id"]

    async with get_session_factory()() as session:
        session.add(
            LedgerEntryModel(
                entry_id="refund-orphan-1",
                wallet_id=wallet_id,
                action="refund",
                amount=Decimal("-100"),
                balance_after=Decimal("-100"),
                description="Refund for PaymentIntent pi_never_minted",
                stripe_event_id="evt_orphan_1",
            )
        )
        session.add(
            LedgerEntryModel(
                entry_id="refund-unlinked-1",
                wallet_id=wallet_id,
                action="refund",
                amount=Decimal("-50"),
                balance_after=Decimal("-150"),
                description="Refund for internal charge ch_9",
            )
        )
        await session.commit()

    summary = await get_agent_money().get_settlement_summary()
    assert summary["minted_count"] == 0
    assert summary["refunded_count"] == 2
    assert Decimal(summary["refunded_total_exact"]) == Decimal("150")
    assert len(summary["orphan_refunds"]) == 1
    assert summary["orphan_refunds"][0]["payment_intent_id"] == "pi_never_minted"
    assert len(summary["unlinked_refunds"]) == 1
