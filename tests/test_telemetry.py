"""
Tests for the Autonomous Product Manager / Telemetry endpoints.
Validates event ingestion, stats, and anomaly listing.
"""

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
def sample_batch():
    return {
        "events": [
            {
                "event_type": "error",
                "source": "iot-bridge",
                "message": "MQTT connection timeout",
                "severity": "high",
                "metadata": {"device_id": "sensor-042"},
            },
            {
                "event_type": "api_call",
                "source": "media-engine",
                "message": "POST /v1/media/videos 200 OK",
                "severity": "info",
                "metadata": {"latency_ms": 142},
            },
            {
                "event_type": "llm_trace",
                "source": "auto-pr",
                "message": "Fix generation completed",
                "severity": "info",
                "metadata": {"model": "claude-3", "tokens": 1500},
            },
        ]
    }


# --- Event Ingestion ---

@pytest.mark.anyio
async def test_batch_ingest(client, api_headers, sample_batch):
    resp = await client.post("/v1/telemetry/events", json=sample_batch, headers=api_headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["ingested"] == 3
    assert data["failed"] == 0
    assert "batch_id" in data


@pytest.mark.anyio
async def test_single_event_ingest(client, api_headers):
    event = {
        "event_type": "warning",
        "source": "auth-service",
        "message": "Rate limit approaching threshold",
        "severity": "medium",
    }
    resp = await client.post("/v1/telemetry/events/single", json=event, headers=api_headers)
    assert resp.status_code == 202
    assert resp.json()["ingested"] == 1


@pytest.mark.anyio
async def test_invalid_event_type(client, api_headers):
    event = {
        "event_type": "invalid_type",
        "source": "test",
        "message": "test",
    }
    resp = await client.post("/v1/telemetry/events/single", json=event, headers=api_headers)
    assert resp.status_code == 422  # Validation error


# --- Stats ---

@pytest.mark.anyio
async def test_stats_endpoint(client, api_headers, sample_batch):
    await client.post("/v1/telemetry/events", json=sample_batch, headers=api_headers)
    resp = await client.get("/v1/telemetry/stats", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_events" in data
    assert "events_by_type" in data


# --- Anomalies ---

@pytest.mark.anyio
async def test_list_anomalies_empty(client, api_headers):
    resp = await client.get("/v1/telemetry/anomalies", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 0
    assert isinstance(data["anomalies"], list)


@pytest.mark.anyio
async def test_anomaly_not_found(client, api_headers):
    resp = await client.get("/v1/telemetry/anomalies/nonexistent", headers=api_headers)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_auto_pr_anomaly_not_found(client, api_headers):
    resp = await client.post(
        "/v1/telemetry/anomalies/nonexistent/auto-pr",
        json={"anomaly_id": "nonexistent", "dry_run": True},
        headers=api_headers,
    )
    assert resp.status_code == 404
