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
    from app.routers.well_known import get_agent_first_metadata

    assert data["agent_first"] == get_agent_first_metadata()
    assert data["docs"].get("dependency_truth") == "/health/dependencies"
    assert data["docs"].get("capability_index") == "/v1/discover"


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
    assert data["agent_first"]["design_principle"] == "agent_first"
    assert data["sections"][0]["path"] == "/.well-known/agent.json"
    assert len(data["services"]) >= 15  # 13 pillars + dashboard + broadcast


@pytest.mark.anyio
async def test_v1_discover_includes_agent_first(client):
    from app.routers.well_known import get_agent_first_metadata

    resp = await client.get("/v1/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_first" in data
    assert data["agent_first"] == get_agent_first_metadata()
    af = data["agent_first"]
    assert af.get("primary_audience") == "autonomous_agents"
    assert af.get("design_principle") == "agent_first"
    assert af.get("simulation_and_dependency_truth") == "/health/dependencies"


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
