"""
Tests for the Genesis Agent Meta-Launch.
Validates that the full A2A lifecycle executes autonomously:
FUND → BUILD → SECURE → TEST → PUBLISH → MONITOR
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


@pytest.mark.anyio
async def test_genesis_completes_all_phases(client):
    """Genesis Agent should complete all 6 phases and report ALIVE."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == "ALIVE"
    assert data["phases_completed"] == 6
    assert data["phases_total"] == 6
    assert len(data["errors"]) == 0
    assert data["genesis_id"].startswith("genesis-")


@pytest.mark.anyio
async def test_genesis_fund_phase(client):
    """Fund phase should create sponsor + child wallet."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    fund = data["fund"]
    assert fund["sponsor_wallet_id"].startswith("spn-")
    assert fund["genesis_wallet_id"].startswith("chd-")
    assert fund["genesis_balance"] == 50000.0
    assert fund["genesis_max_spend"] == 50000.0


@pytest.mark.anyio
async def test_genesis_build_phase(client):
    """Build phase should generate a micro-service with endpoints."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    build = data["build"]
    assert build["service_name"] == "genesis-widget-api"
    assert build["endpoints_generated"] >= 5
    assert build["source_lines"] > 20


@pytest.mark.anyio
async def test_genesis_secure_phase(client):
    """Secure phase should RTaaS-scan all endpoints."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    secure = data["secure"]
    assert secure["rtaas_job_id"].startswith("rtaas-")
    assert secure["targets_scanned"] == 6
    assert 0 <= secure["security_score"] <= 100
    assert secure["remediation_actions"] >= 0


@pytest.mark.anyio
async def test_genesis_test_phase(client):
    """Test phase should evaluate in a sandbox."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    test = data["test"]
    assert test["sandbox_env_id"].startswith("env-")
    assert test["env_type"] == "api_mock"
    assert test["steps_used"] >= 1
    assert 0 <= test["generalization_score"] <= 100


@pytest.mark.anyio
async def test_genesis_publish_phase(client):
    """Publish phase should generate llm.txt + OpenAPI + agent.json."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    publish = data["publish"]
    assert publish["generation_id"].startswith("gen-")
    assert publish["endpoints_documented"] >= 5
    assert publish["llm_txt_lines"] > 10
    assert publish["openapi_paths"] >= 2
    assert publish["agent_json_capabilities"] >= 5


@pytest.mark.anyio
async def test_genesis_monitor_phase(client):
    """Monitor phase should create telemetry pipeline and ingest events."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    monitor = data["monitor"]
    assert monitor["pipeline_id"].startswith("pipe-")
    assert monitor["events_ingested"] == 5
    assert monitor["anomalies_detected"] == 0  # Clean startup


@pytest.mark.anyio
async def test_genesis_custom_config(client):
    """Genesis should accept custom configuration."""
    resp = await client.post("/v1/launch/genesis", json={
        "sponsor_name": "Custom Sponsor",
        "seed_capital_usd": 200.0,
        "genesis_budget_credits": 80000.0,
        "genesis_max_spend": 80000.0,
        "target_service_name": "custom-agent-api",
    }, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == "ALIVE"
    assert data["build"]["service_name"] == "custom-agent-api"
    assert data["fund"]["genesis_max_spend"] == 80000.0


@pytest.mark.anyio
async def test_genesis_tracks_spend(client):
    """Genesis should track total credits spent and remaining."""
    resp = await client.post("/v1/launch/genesis", json={}, headers=HEADERS)
    data = resp.json()

    # Genesis agent should have some balance remaining (it's not charged per-action in sim)
    assert data["credits_remaining"] >= 0
    assert isinstance(data["total_credits_spent"], (int, float))


@pytest.mark.anyio
async def test_genesis_requires_api_key(client):
    """Genesis must require authentication."""
    resp = await client.post("/v1/launch/genesis", json={})
    assert resp.status_code in (401, 403)
