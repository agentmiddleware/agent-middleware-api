"""
Tests for Pillar 10: Sub-Wallet Provisioning (Swarm Delegation).
Validates hierarchical child wallets, spend caps, and reclaim.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


HEADERS = {"X-API-Key": "test-key"}


async def _create_sponsor_and_agent(client):
    """Helper: create sponsor + agent wallet chain."""
    sponsor = await client.post("/v1/billing/wallets/sponsor", json={
        "sponsor_name": "Swarm Corp",
        "email": "swarm@test.com",
        "initial_credits": 100000.0,
    }, headers=HEADERS)
    sponsor_id = sponsor.json()["wallet_id"]

    agent = await client.post("/v1/billing/wallets/agent", json={
        "sponsor_wallet_id": sponsor_id,
        "agent_id": "master-builder-01",
        "budget_credits": 50000.0,
    }, headers=HEADERS)
    agent_id = agent.json()["wallet_id"]

    return sponsor_id, agent_id


@pytest.mark.anyio
async def test_create_child_wallet(client):
    """Agent can spawn a child wallet."""
    _, agent_id = await _create_sponsor_and_agent(client)

    resp = await client.post("/v1/billing/wallets/child", json={
        "parent_wallet_id": agent_id,
        "child_agent_id": "code-writer-01",
        "budget_credits": 2000.0,
        "max_spend": 2000.0,
        "task_description": "Write unit tests",
    }, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["wallet_type"] == "child"
    assert data["balance"] == 2000.0
    assert data["max_spend"] == 2000.0
    assert data["child_agent_id"] == "code-writer-01"


@pytest.mark.anyio
async def test_child_wallet_deducts_from_parent(client):
    """Spawning a child deducts credits from parent."""
    _, agent_id = await _create_sponsor_and_agent(client)

    await client.post("/v1/billing/wallets/child", json={
        "parent_wallet_id": agent_id,
        "child_agent_id": "tester-01",
        "budget_credits": 5000.0,
        "max_spend": 5000.0,
    }, headers=HEADERS)

    parent = await client.get(f"/v1/billing/wallets/{agent_id}", headers=HEADERS)
    assert parent.json()["balance"] == 45000.0  # 50K - 5K


@pytest.mark.anyio
async def test_reclaim_child_wallet(client):
    """Reclaim unspent credits from child back to parent."""
    _, agent_id = await _create_sponsor_and_agent(client)

    child_resp = await client.post("/v1/billing/wallets/child", json={
        "parent_wallet_id": agent_id,
        "child_agent_id": "deployer-01",
        "budget_credits": 3000.0,
        "max_spend": 3000.0,
    }, headers=HEADERS)
    child_id = child_resp.json()["wallet_id"]

    reclaim = await client.post(f"/v1/billing/wallets/{child_id}/reclaim", headers=HEADERS)
    assert reclaim.status_code == 200
    data = reclaim.json()
    assert data["credits_reclaimed"] == 3000.0
    assert data["child_status"] == "closed"


@pytest.mark.anyio
async def test_swarm_budget_summary(client):
    """View hierarchical budget for agent's child swarm."""
    _, agent_id = await _create_sponsor_and_agent(client)

    for i in range(3):
        await client.post("/v1/billing/wallets/child", json={
            "parent_wallet_id": agent_id,
            "child_agent_id": f"worker-{i}",
            "budget_credits": 1000.0,
            "max_spend": 1000.0,
        }, headers=HEADERS)

    resp = await client.get(f"/v1/billing/wallets/{agent_id}/swarm", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_children"] == 3
    assert data["total_delegated"] == 3000.0
    assert len(data["children"]) == 3


@pytest.mark.anyio
async def test_child_wallet_insufficient_parent_balance(client):
    """Cannot spawn child wallet exceeding parent balance."""
    _, agent_id = await _create_sponsor_and_agent(client)

    resp = await client.post("/v1/billing/wallets/child", json={
        "parent_wallet_id": agent_id,
        "child_agent_id": "greedy-agent",
        "budget_credits": 999999.0,
        "max_spend": 999999.0,
    }, headers=HEADERS)
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_child_wallet_requires_api_key(client):
    resp = await client.post("/v1/billing/wallets/child", json={
        "parent_wallet_id": "fake",
        "child_agent_id": "test",
        "budget_credits": 100.0,
        "max_spend": 100.0,
    })
    assert resp.status_code in (401, 403)
