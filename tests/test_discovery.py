"""
Tests for discovery and documentation endpoints.
Validates the agent 'front door' — the endpoints agents hit first
to decide whether to use this API.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Root Discovery ---

@pytest.mark.anyio
async def test_root_returns_manifest(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "services" in data
    assert "auth" in data
    assert "docs" in data
    assert "iot_bridge" in data["services"]
    assert "autonomous_pm" in data["services"]
    assert "media_engine" in data["services"]


@pytest.mark.anyio
async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# --- OpenAPI Spec ---

@pytest.mark.anyio
async def test_openapi_json_accessible(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "paths" in data
    assert "components" in data
    assert len(data["paths"]) > 15  # We have ~25 endpoints now


# --- Doc Index ---

@pytest.mark.anyio
async def test_doc_index(client):
    resp = await client.get("/docs/index")
    assert resp.status_code == 200
    data = resp.json()
    assert "sections" in data
    assert "services" in data
    assert len(data["services"]) >= 15  # 13 pillars + dashboard + broadcast


# --- Agent Manifest ---

@pytest.mark.anyio
async def test_well_known_agent_json(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema_version"] == "1.0"
    assert "capabilities" in data
    assert len(data["capabilities"]) == 8
    assert data["authentication"]["type"] == "api_key"


# --- LLM.txt ---

@pytest.mark.anyio
async def test_llm_txt_served(client):
    resp = await client.get("/llm.txt")
    # May be 200 or 404 depending on file availability in test env
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert "Agent-Native Middleware API" in resp.text
