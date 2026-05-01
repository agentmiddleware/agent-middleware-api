"""
Tests for the Real-Time Dashboard API.
Validates aggregate metrics from all 15 pillars.
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


# --- Full Snapshot ---

@pytest.mark.anyio
async def test_dashboard_snapshot(client):
    """Full platform snapshot returns all sections."""
    resp = await client.get("/v1/dashboard", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform_status"] == "OPERATIONAL"
    assert data["pillars_active"] == 15
    assert "economics" in data
    assert "wallet_tree" in data
    assert "security" in data
    assert "telemetry" in data
    assert "sandbox" in data
    assert "protocol" in data
    assert "genesis_launches" in data


@pytest.mark.anyio
async def test_dashboard_economics_endpoint(client):
    """Economics sub-endpoint returns wallet metrics."""
    resp = await client.get("/v1/dashboard/economics", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_sponsors" in data
    assert "total_agent_wallets" in data
    assert "total_child_wallets" in data
    assert "credit_velocity" in data
    assert "wallet_tree" in data


@pytest.mark.anyio
async def test_dashboard_security_endpoint(client):
    """Security sub-endpoint returns aggregate posture."""
    resp = await client.get("/v1/dashboard/security", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_jobs" in data
    assert "total_vulnerabilities" in data
    assert "avg_security_score" in data
    assert "most_common_category" in data


@pytest.mark.anyio
async def test_dashboard_telemetry_endpoint(client):
    """Telemetry sub-endpoint returns pipeline health."""
    resp = await client.get("/v1/dashboard/telemetry", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_pipelines" in data
    assert "total_events" in data
    assert "avg_error_rate" in data


@pytest.mark.anyio
async def test_dashboard_genesis_endpoint(client):
    """Genesis sub-endpoint returns launch history."""
    resp = await client.get("/v1/dashboard/genesis", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_launches"] == 0
    assert data["alive"] == 0
    assert data["reports"] == []


@pytest.mark.anyio
async def test_dashboard_after_genesis(client):
    """Dashboard reflects Genesis launch when one has occurred."""
    # Fire a genesis launch
    await client.post("/v1/launch/genesis", json={}, headers=HEADERS)

    # Dashboard should show the genesis data in economics
    resp = await client.get("/v1/dashboard/economics", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    # After genesis, there should be wallets
    assert data["total_sponsors"] >= 1
    assert data["total_agent_wallets"] >= 1
    assert data["total_child_wallets"] >= 1


@pytest.mark.anyio
async def test_dashboard_requires_api_key(client):
    """Dashboard requires authentication."""
    resp = await client.get("/v1/dashboard")
    assert resp.status_code in (401, 403)
