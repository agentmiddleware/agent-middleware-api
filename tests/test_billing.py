"""
Tests for Agent Financial Gateways (Billing Service).
Validates the full money flow: sponsor wallets → agent provisioning →
micro-metering → 402 insufficient funds → top-ups → arbitrage reporting.
"""

import pytest
from decimal import Decimal
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


# --- Sponsor Wallet ---

@pytest.mark.anyio
async def test_create_sponsor_wallet(client, api_headers):
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Acme Corp",
            "email": "billing@acme.com",
            "initial_credits": 50000.0,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["wallet_type"] == "sponsor"
    assert data["owner_name"] == "Acme Corp"
    assert data["balance"] == 50000.0
    assert Decimal(data["balance_exact"]) == Decimal("50000")
    assert data["wallet_id"].startswith("spn-")
    assert data["status"] == "active"


@pytest.mark.anyio
async def test_create_sponsor_zero_balance(client, api_headers):
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Broke Corp", "email": "a@b.com"},
        headers=api_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["balance"] == 0.0


# --- Agent Wallet Provisioning ---

@pytest.mark.anyio
async def test_provision_agent_wallet(client, api_headers):
    # Create sponsor first
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Test Sponsor", "email": "s@t.com", "initial_credits": 20000},
        headers=api_headers,
    )
    sponsor_id = sponsor_resp.json()["wallet_id"]

    # Provision agent
    resp = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": "agent-crawl-bot-42",
            "budget_credits": 5000.0,
            "daily_limit": 1000.0,
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["wallet_type"] == "agent"
    assert data["balance"] == 5000.0
    assert data["daily_limit"] == 1000.0
    assert data["sponsor_wallet_id"] == sponsor_id
    assert data["agent_id"] == "agent-crawl-bot-42"
    assert data["wallet_id"].startswith("agt-")

    # Verify sponsor balance reduced
    sponsor_check = await client.get(
        f"/v1/billing/wallets/{sponsor_id}",
        headers=api_headers,
    )
    assert sponsor_check.json()["balance"] == 15000.0


@pytest.mark.anyio
async def test_provision_insufficient_sponsor_balance(client, api_headers):
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Low Funds", "email": "l@f.com", "initial_credits": 100},
        headers=api_headers,
    )
    sponsor_id = sponsor_resp.json()["wallet_id"]

    resp = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": sponsor_id, "agent_id": "greedy-bot", "budget_credits": 50000},
        headers=api_headers,
    )
    assert resp.status_code == 400
    assert "insufficient" in resp.json()["detail"]["message"].lower()


# --- Charging (Micro-Metering) ---

@pytest.mark.anyio
async def test_charge_agent_wallet(client, api_headers):
    # Setup: sponsor → agent
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Charge Test", "email": "c@t.com", "initial_credits": 10000},
        headers=api_headers,
    )
    sponsor_id = sponsor_resp.json()["wallet_id"]

    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": sponsor_id, "agent_id": "metered-bot", "budget_credits": 5000},
        headers=api_headers,
    )
    agent_wallet_id = agent_resp.json()["wallet_id"]

    # Charge for IoT bridge usage (2 credits per request × 10 units = 20 credits)
    resp = await client.post(
        f"/v1/billing/charge?wallet_id={agent_wallet_id}&service=iot_bridge&units=10&request_path=POST+/v1/iot/devices",
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "debit"
    assert data["amount"] == -20.0  # 10 units × 2 credits
    assert Decimal(data["amount_exact"]) == Decimal("-20")
    assert data["balance_after"] == 4980.0
    assert Decimal(data["balance_after_exact"]) == Decimal("4980")
    assert data["service_category"] == "iot_bridge"
    assert data["compute_cost"] is not None
    assert data["margin"] is not None
    assert data["margin"] > 0  # Arbitrage should be positive


@pytest.mark.anyio
async def test_charge_insufficient_funds_returns_402(client, api_headers):
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Empty", "email": "e@t.com", "initial_credits": 100},
        headers=api_headers,
    )
    sponsor_id = sponsor_resp.json()["wallet_id"]

    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": sponsor_id, "agent_id": "broke-bot", "budget_credits": 10},
        headers=api_headers,
    )
    agent_wallet_id = agent_resp.json()["wallet_id"]

    # Try to charge more than balance (red_team scan = 100 credits)
    resp = await client.post(
        f"/v1/billing/charge?wallet_id={agent_wallet_id}&service=red_team&units=1",
        headers=api_headers,
    )
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["error"] == "insufficient_funds"
    assert detail["wallet_id"] == agent_wallet_id
    assert "top_up_url" in detail
    assert detail["shortfall"] > 0


# --- Ledger ---

@pytest.mark.anyio
async def test_ledger_records_transactions(client, api_headers):
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Ledger Test", "email": "l@t.com", "initial_credits": 5000},
        headers=api_headers,
    )
    sponsor_id = sponsor_resp.json()["wallet_id"]

    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": sponsor_id, "agent_id": "ledger-bot", "budget_credits": 2000},
        headers=api_headers,
    )
    agent_wallet_id = agent_resp.json()["wallet_id"]

    # Make a charge
    await client.post(
        f"/v1/billing/charge?wallet_id={agent_wallet_id}&service=agent_comms&units=5",
        headers=api_headers,
    )

    # Check ledger
    resp = await client.get(
        f"/v1/billing/ledger/{agent_wallet_id}",
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["wallet_id"] == agent_wallet_id
    assert data["total"] >= 2  # At least transfer in + debit
    assert data["period_debits"] > 0
    assert "period_debits_exact" in data

    # Verify debit entry exists
    debits = [e for e in data["entries"] if e["action"] == "debit"]
    assert len(debits) >= 1
    assert debits[0]["service_category"] == "agent_comms"
    assert debits[0]["amount_exact"].startswith("-")


# --- Top-Up ---

@pytest.mark.anyio
async def test_top_up_sponsor(client, api_headers):
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Topup Test", "email": "t@t.com", "initial_credits": 0},
        headers=api_headers,
    )
    wallet_id = sponsor_resp.json()["wallet_id"]

    resp = await client.post(
        "/v1/billing/top-up",
        json={"wallet_id": wallet_id, "amount_fiat": 50.0},
        headers=api_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["amount_fiat"] == 50.0
    assert data["credits_added"] == 50000.0  # $50 × 1000 credits/$
    assert data["exchange_rate"] == 1000.0
    assert data["status"] == "completed"

    # Verify balance updated
    wallet = await client.get(f"/v1/billing/wallets/{wallet_id}", headers=api_headers)
    assert wallet.json()["balance"] == 50000.0


@pytest.mark.anyio
async def test_top_up_agent_wallet_fails(client, api_headers):
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "S", "email": "s@t.com", "initial_credits": 5000},
        headers=api_headers,
    )
    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": sponsor_resp.json()["wallet_id"], "agent_id": "a", "budget_credits": 1000},
        headers=api_headers,
    )

    resp = await client.post(
        "/v1/billing/top-up",
        json={"wallet_id": agent_resp.json()["wallet_id"], "amount_fiat": 10.0},
        headers=api_headers,
    )
    assert resp.status_code == 400


# --- Pricing Table ---

@pytest.mark.anyio
async def test_pricing_table(client, api_headers):
    resp = await client.get("/v1/billing/pricing", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["exchange_rate"] == 1000.0
    assert len(data["pricing"]) >= 7  # At least one entry per service
    # Check structure
    entry = data["pricing"][0]
    assert "service_category" in entry
    assert "unit" in entry
    assert "credits_per_unit" in entry


# --- Arbitrage Report ---

@pytest.mark.anyio
async def test_arbitrage_report(client, api_headers):
    # Create wallet chain and make some charges
    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Arb Test", "email": "a@t.com", "initial_credits": 100000},
        headers=api_headers,
    )
    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": sponsor_resp.json()["wallet_id"], "agent_id": "arb-bot", "budget_credits": 50000},
        headers=api_headers,
    )
    wallet_id = agent_resp.json()["wallet_id"]

    # Generate some revenue across services
    await client.post(f"/v1/billing/charge?wallet_id={wallet_id}&service=iot_bridge&units=100", headers=api_headers)
    await client.post(f"/v1/billing/charge?wallet_id={wallet_id}&service=content_factory&units=5", headers=api_headers)
    await client.post(f"/v1/billing/charge?wallet_id={wallet_id}&service=media_engine&units=200", headers=api_headers)

    resp = await client.get("/v1/billing/arbitrage", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_revenue"] > 0
    assert data["total_compute_cost"] > 0
    assert data["gross_margin"] > 0
    assert data["margin_percentage"] > 0
    assert len(data["by_service"]) >= 1
    assert len(data["top_profitable_actions"]) >= 1


# --- Wallet Listing ---

@pytest.mark.anyio
async def test_list_wallets(client, api_headers):
    await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "List Test", "email": "l@t.com", "initial_credits": 1000},
        headers=api_headers,
    )
    resp = await client.get("/v1/billing/wallets", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.anyio
async def test_list_wallets_by_type(client, api_headers):
    resp = await client.get(
        "/v1/billing/wallets?wallet_type=sponsor",
        headers=api_headers,
    )
    assert resp.status_code == 200
    for w in resp.json()["wallets"]:
        assert w["wallet_type"] == "sponsor"


@pytest.mark.anyio
async def test_get_wallet_not_found(client, api_headers):
    resp = await client.get("/v1/billing/wallets/nonexistent", headers=api_headers)
    assert resp.status_code == 404


# --- Alerts ---

@pytest.mark.anyio
async def test_billing_alerts(client, api_headers):
    resp = await client.get("/v1/billing/alerts", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert "total" in data
    assert "unacknowledged" in data


# --- Auth ---

@pytest.mark.anyio
async def test_billing_requires_api_key(client):
    resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "NoKey", "email": "n@k.com"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_charge_requires_api_key(client):
    resp = await client.post("/v1/billing/charge?wallet_id=x&service=iot_bridge")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_db_key_cannot_operate_on_other_wallet(client, api_headers):
    wallet_a_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Tenant A", "email": "a@test.com", "initial_credits": 1000},
        headers=api_headers,
    )
    wallet_b_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Tenant B", "email": "b@test.com", "initial_credits": 1000},
        headers=api_headers,
    )
    wallet_a = wallet_a_resp.json()["wallet_id"]
    wallet_b = wallet_b_resp.json()["wallet_id"]

    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_a},
        headers=api_headers,
    )
    db_headers = {"X-API-Key": key_resp.json()["api_key"]}

    blocked_requests = [
        client.get(f"/v1/billing/wallets/{wallet_b}", headers=db_headers),
        client.get(f"/v1/billing/ledger/{wallet_b}", headers=db_headers),
        client.post(
            f"/v1/billing/charge?wallet_id={wallet_b}&service=iot_bridge",
            headers=db_headers,
        ),
        client.post(
            "/v1/billing/top-up",
            json={"wallet_id": wallet_b, "amount_fiat": 1.0},
            headers=db_headers,
        ),
        client.post(
            f"/v1/billing/transfer?from_wallet_id={wallet_b}&to_wallet_id={wallet_a}&amount=1",
            headers=db_headers,
        ),
        client.get(f"/v1/billing/alerts?wallet_id={wallet_b}", headers=db_headers),
        client.get(f"/v1/billing/wallets/{wallet_b}/velocity", headers=db_headers),
        client.post(
            "/v1/billing/dry-run/session",
            json={"wallet_id": wallet_b},
            headers=db_headers,
        ),
    ]

    for request in blocked_requests:
        resp = await request
        assert resp.status_code == 403

    own_resp = await client.get(f"/v1/billing/wallets/{wallet_a}", headers=db_headers)
    assert own_resp.status_code == 200


@pytest.mark.anyio
async def test_bootstrap_key_can_manage_multiple_wallets(client, api_headers):
    wallet_a_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Admin A", "email": "admin-a@test.com"},
        headers=api_headers,
    )
    wallet_b_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Admin B", "email": "admin-b@test.com"},
        headers=api_headers,
    )

    for wallet_id in (
        wallet_a_resp.json()["wallet_id"],
        wallet_b_resp.json()["wallet_id"],
    ):
        resp = await client.get(f"/v1/billing/wallets/{wallet_id}", headers=api_headers)
        assert resp.status_code == 200

        key_resp = await client.post(
            "/v1/api-keys",
            json={"wallet_id": wallet_id},
            headers=api_headers,
        )
        assert key_resp.status_code == 201
