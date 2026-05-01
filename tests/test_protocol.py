"""
Tests for Pillar 11: Protocol Generation Engine.
Validates code-to-discovery pipeline.
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

SAMPLE_CODE = '''
from fastapi import APIRouter
router = APIRouter()

@router.get("/api/v1/widgets", summary="List widgets", description="Get all widgets")
async def list_widgets():
    return []

@router.post("/api/v1/widgets", summary="Create widget", description="Create a new widget")
async def create_widget():
    return {"id": "w1"}

@router.get("/api/v1/widgets/{widget_id}", summary="Get widget", description="Get widget by ID")
async def get_widget(widget_id: str):
    return {}
'''


@pytest.mark.anyio
async def test_generate_protocol(client):
    """Full protocol generation from source code."""
    resp = await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "widget-api",
        "service_version": "2.0.0",
        "base_url": "https://api.widgets.io",
    }, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()

    assert data["endpoints_parsed"] == 3
    assert "widget-api" in data["llm_txt"]
    assert data["openapi_spec"]["openapi"] == "3.1.0"
    assert data["agent_json"]["schema_version"] == "1.0"
    assert data["generation_id"].startswith("gen-")


@pytest.mark.anyio
async def test_llm_txt_contains_endpoints(client):
    """Generated llm.txt should list all parsed endpoints."""
    resp = await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "widget-api",
    }, headers=HEADERS)
    data = resp.json()
    llm_txt = data["llm_txt"]
    assert "GET /api/v1/widgets" in llm_txt
    assert "POST /api/v1/widgets" in llm_txt
    assert "List widgets" in llm_txt


@pytest.mark.anyio
async def test_openapi_spec_structure(client):
    """OpenAPI spec should have paths, security, and info."""
    resp = await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "test-api",
    }, headers=HEADERS)
    spec = resp.json()["openapi_spec"]
    assert "paths" in spec
    assert "/api/v1/widgets" in spec["paths"]
    assert "components" in spec
    assert "securitySchemes" in spec["components"]


@pytest.mark.anyio
async def test_agent_json_manifest(client):
    """agent.json should list capabilities and auth."""
    resp = await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "agent-test",
        "base_url": "https://api.test.com",
    }, headers=HEADERS)
    aj = resp.json()["agent_json"]
    assert aj["name"] == "agent-test"
    assert aj["base_url"] == "https://api.test.com"
    assert len(aj["capabilities"]) == 3
    assert aj["auth"]["type"] == "api_key"


@pytest.mark.anyio
async def test_empty_code_warns(client):
    """Source code with no endpoints should generate a warning."""
    resp = await client.post("/v1/protocol/generate", json={
        "source_code": "# empty file\nprint('hello')",
        "service_name": "empty-api",
    }, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["endpoints_parsed"] == 0
    assert len(data["warnings"]) > 0


@pytest.mark.anyio
async def test_list_generations(client):
    """Historical generations should be retrievable."""
    await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "gen-list-test",
    }, headers=HEADERS)

    resp = await client.get("/v1/protocol/generations", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.anyio
async def test_get_generation_by_id(client):
    """Can retrieve a specific generation by ID."""
    create = await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "id-test",
    }, headers=HEADERS)
    gen_id = create.json()["generation_id"]

    resp = await client.get(f"/v1/protocol/generations/{gen_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["generation_id"] == gen_id


@pytest.mark.anyio
async def test_generation_not_found(client):
    resp = await client.get("/v1/protocol/generations/gen-nonexistent", headers=HEADERS)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_protocol_requires_api_key(client):
    resp = await client.post("/v1/protocol/generate", json={
        "source_code": SAMPLE_CODE,
        "service_name": "test",
    })
    assert resp.status_code in (401, 403)
