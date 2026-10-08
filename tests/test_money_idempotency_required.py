"""Money-movement idempotency: required key, same-key replay, Stripe passthrough.

A retried charge, transfer, or fiat top-up prepare without an
Idempotency-Key cannot be told apart from a new request, so the server
would move money twice. These tests pin the fix: the key is required by
default, a same-key retry replays the original result without moving
money again, and the prepare key reaches Stripe's PaymentIntent creation.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import get_settings
from app.main import app

# Transfer and top-up prepare live on the dormant billing expansion router,
# which the suite mounts only for marked tests (see tests/conftest.py).
pytestmark = pytest.mark.dormant


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


@pytest.fixture
async def funded_agent(client, api_headers, clean_database):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Idem Required",
            "email": "idem-required@t.com",
            "initial_credits": 10000,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201
    sponsor_id = sponsor.json()["wallet_id"]
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "idem-required-bot",
            "budget_credits": 5000,
        },
        headers=api_headers,
    )
    assert agent.status_code == 201
    return agent.json()["wallet_id"]


def _relax_idempotency_requirement(monkeypatch):
    monkeypatch.setenv("REQUIRE_IDEMPOTENCY_KEY", "false")
    get_settings.cache_clear()


def _restore_idempotency_requirement(monkeypatch):
    monkeypatch.delenv("REQUIRE_IDEMPOTENCY_KEY", raising=False)
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_charge_without_key_is_rejected(client, api_headers, funded_agent):
    resp = await client.post(
        f"/v1/billing/charge?wallet_id={funded_agent}&service=iot_bridge&units=10",
        headers=api_headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "missing_idempotency_key"
    assert "Idempotency-Key" in detail["message"]

    wallet = await client.get(
        f"/v1/billing/wallets/{funded_agent}", headers=api_headers
    )
    assert wallet.json()["balance"] == 5000.0


@pytest.mark.anyio
async def test_transfer_without_key_is_rejected(client, api_headers, funded_agent):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Idem Required Dest",
            "email": "idem-required-dest@t.com",
            "initial_credits": 10000,
        },
        headers=api_headers,
    )
    dest_agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor.json()["wallet_id"],
            "agent_id": "idem-required-dest",
            "budget_credits": 100,
        },
        headers=api_headers,
    )
    dest_id = dest_agent.json()["wallet_id"]

    resp = await client.post(
        f"/v1/billing/transfer?from_wallet_id={funded_agent}"
        f"&to_wallet_id={dest_id}&amount=100",
        headers=api_headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "missing_idempotency_key"
    assert "Idempotency-Key" in detail["message"]

    wallet = await client.get(
        f"/v1/billing/wallets/{funded_agent}", headers=api_headers
    )
    assert wallet.json()["balance"] == 5000.0


@pytest.mark.anyio
async def test_prepare_without_key_is_rejected_and_never_reaches_stripe(
    client, api_headers, funded_agent
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Idem Prepare",
            "email": "idem-prepare@t.com",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    sponsor_id = sponsor.json()["wallet_id"]

    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        resp = await client.post(
            f"/v1/billing/top-up/prepare?wallet_id={sponsor_id}&amount_fiat=50.0",
            headers=api_headers,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "missing_idempotency_key"
    mock_create.assert_not_called()


@pytest.mark.anyio
async def test_charge_without_key_succeeds_when_requirement_relaxed(
    client, api_headers, funded_agent, monkeypatch
):
    _relax_idempotency_requirement(monkeypatch)
    try:
        resp = await client.post(
            f"/v1/billing/charge?wallet_id={funded_agent}&service=iot_bridge&units=10",
            headers=api_headers,
        )
        assert resp.status_code == 200
    finally:
        _restore_idempotency_requirement(monkeypatch)


@pytest.mark.anyio
async def test_transfer_same_key_replays_same_result_and_moves_once(
    client, api_headers, clean_database
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Xfer Replay",
            "email": "xfer-replay@t.com",
            "initial_credits": 10000,
        },
        headers=api_headers,
    )
    src_sponsor = sponsor.json()["wallet_id"]
    agent_a = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": src_sponsor,
            "agent_id": "xfer-replay-a",
            "budget_credits": 5000,
        },
        headers=api_headers,
    )
    agent_b = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": src_sponsor,
            "agent_id": "xfer-replay-b",
            "budget_credits": 100,
        },
        headers=api_headers,
    )
    a = agent_a.json()["wallet_id"]
    b = agent_b.json()["wallet_id"]

    headers = {**api_headers, "Idempotency-Key": "xfer-same-result-1"}
    url = f"/v1/billing/transfer?from_wallet_id={a}&to_wallet_id={b}&amount=1000"

    first = await client.post(url, headers=headers)
    assert first.status_code == 200
    second = await client.post(url, headers=headers)
    assert second.status_code == 200
    # Same logical result: the stored replay renders Decimal amounts as
    # strings where the live response renders floats, so compare the receipt
    # identity and the terminal status, not the raw body.
    assert second.json()["transfer_id"] == first.json()["transfer_id"]
    assert second.json()["status"] == first.json()["status"] == "completed"

    wallet_a = await client.get(f"/v1/billing/wallets/{a}", headers=api_headers)
    wallet_b = await client.get(f"/v1/billing/wallets/{b}", headers=api_headers)
    assert wallet_a.json()["balance"] == 4000.0
    assert wallet_b.json()["balance"] == 1100.0


@pytest.mark.anyio
async def test_prepare_same_key_returns_same_intent_and_calls_stripe_once(
    client, api_headers, clean_database
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Prepare Replay",
            "email": "prepare-replay@t.com",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    headers = {**api_headers, "Idempotency-Key": "prepare-replay-1"}
    url = f"/v1/billing/top-up/prepare?wallet_id={wallet_id}&amount_fiat=50.0"

    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        mock_create.return_value = MagicMock(
            id="pi_replay123",
            client_secret="pi_replay123_secret_xyz",
            status="requires_payment_method",
        )
        first = await client.post(url, headers=headers)
        assert first.status_code == 200
        second = await client.post(url, headers=headers)
        assert second.status_code == 200
        assert second.json() == first.json()
        assert first.json()["payment_intent_id"] == "pi_replay123"
        mock_create.assert_called_once()


@pytest.mark.anyio
async def test_prepare_forwards_idempotency_key_to_stripe(
    client, api_headers, clean_database
):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Prepare Forward",
            "email": "prepare-forward@t.com",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    wallet_id = sponsor.json()["wallet_id"]

    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        mock_create.return_value = MagicMock(
            id="pi_forward123",
            client_secret="pi_forward123_secret_xyz",
            status="requires_payment_method",
        )
        resp = await client.post(
            f"/v1/billing/top-up/prepare?wallet_id={wallet_id}&amount_fiat=10.0",
            headers={**api_headers, "Idempotency-Key": "prepare-forward-1"},
        )
        assert resp.status_code == 200
        assert mock_create.call_args.kwargs["idempotency_key"] == ("prepare-forward-1")
