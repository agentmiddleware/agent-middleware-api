"""
Tests for Oracle Mass-Broadcast API.
Validates multi-directory broadcasting and discovery metrics.
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


# --- Broadcast ---

@pytest.mark.anyio
async def test_broadcast_api(client):
    """Broadcast a service to all directories."""
    resp = await client.post(
        "/v1/broadcast",
        json={
            "service_name": "test-widget-api",
            "base_url": "https://api.test.com",
            "generation_id": "gen-abc123",
            "llm_txt": "# Test Widget API\n> Endpoints...",
            "openapi_spec": {"openapi": "3.1.0", "info": {"title": "Test"}},
            "agent_json": {"name": "test-widget-api", "capabilities": []},
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_id"].startswith("bcast-")
    assert data["service_name"] == "test-widget-api"
    assert data["directories_contacted"] == 6  # All 6 directories
    assert data["directories_confirmed"] >= 1
    assert data["status"] in ("complete", "partial")
    assert "discovery_metrics" in data


@pytest.mark.anyio
async def test_broadcast_with_specific_directories(client):
    """Broadcast to specific directories only."""
    resp = await client.post(
        "/v1/broadcast",
        json={
            "service_name": "targeted-api",
            "base_url": "https://api.targeted.com",
            "generation_id": "gen-targeted",
            "agent_json": {"name": "targeted-api"},
            "target_directories": ["agent-protocol-registry", "anthropic-mcp-registry"],
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["directories_contacted"] == 2


@pytest.mark.anyio
async def test_list_broadcast_jobs(client):
    """List all broadcast jobs."""
    # Create a job first
    await client.post(
        "/v1/broadcast",
        json={
            "service_name": "list-test-api",
            "base_url": "https://api.list.com",
            "generation_id": "gen-list",
        },
        headers=HEADERS,
    )
    resp = await client.get("/v1/broadcast/jobs", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.anyio
async def test_get_broadcast_job(client):
    """Get specific broadcast job details."""
    create_resp = await client.post(
        "/v1/broadcast",
        json={
            "service_name": "detail-api",
            "base_url": "https://api.detail.com",
            "generation_id": "gen-detail",
            "llm_txt": "# Detail API",
        },
        headers=HEADERS,
    )
    job_id = create_resp.json()["job_id"]

    resp = await client.get(f"/v1/broadcast/jobs/{job_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert len(data["targets"]) > 0


@pytest.mark.anyio
async def test_get_discovery_metrics(client):
    """Get discovery metrics for a broadcast job."""
    create_resp = await client.post(
        "/v1/broadcast",
        json={
            "service_name": "metrics-api",
            "base_url": "https://api.metrics.com",
            "generation_id": "gen-metrics",
            "openapi_spec": {"openapi": "3.1.0"},
        },
        headers=HEADERS,
    )
    job_id = create_resp.json()["job_id"]

    resp = await client.get(f"/v1/broadcast/jobs/{job_id}/metrics", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "impressions" in data
    assert "lookups" in data
    assert "integrations" in data
    assert "referral_sources" in data


@pytest.mark.anyio
async def test_simulate_discovery_event(client):
    """Simulate discovery events and verify metrics update."""
    create_resp = await client.post(
        "/v1/broadcast",
        json={
            "service_name": "events-api",
            "base_url": "https://api.events.com",
            "generation_id": "gen-events",
            "llm_txt": "# Events API",
        },
        headers=HEADERS,
    )
    job_id = create_resp.json()["job_id"]

    # Get baseline
    baseline = await client.get(f"/v1/broadcast/jobs/{job_id}/metrics", headers=HEADERS)
    base_impressions = baseline.json()["impressions"]

    # Simulate an impression
    resp = await client.post(
        f"/v1/broadcast/jobs/{job_id}/events",
        json={"event_type": "impression", "source": "langchain-hub"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["impressions"] == base_impressions + 1
    assert "langchain-hub" in data["referral_sources"]


@pytest.mark.anyio
async def test_list_directories(client):
    """List available broadcast directories."""
    resp = await client.get("/v1/broadcast/directories", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert any(d["id"] == "anthropic-mcp-registry" for d in data["directories"])


@pytest.mark.anyio
async def test_broadcast_job_not_found(client):
    """404 for non-existent broadcast job."""
    resp = await client.get("/v1/broadcast/jobs/bcast-nonexistent", headers=HEADERS)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_invalid_event_type(client):
    """Reject invalid discovery event types."""
    create_resp = await client.post(
        "/v1/broadcast",
        json={
            "service_name": "invalid-api",
            "base_url": "https://api.invalid.com",
            "generation_id": "gen-invalid",
        },
        headers=HEADERS,
    )
    job_id = create_resp.json()["job_id"]

    resp = await client.post(
        f"/v1/broadcast/jobs/{job_id}/events",
        json={"event_type": "invalid_type", "source": "test"},
        headers=HEADERS,
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_broadcast_requires_api_key(client):
    """Broadcast requires authentication."""
    resp = await client.post("/v1/broadcast", json={})
    assert resp.status_code in (401, 403)
