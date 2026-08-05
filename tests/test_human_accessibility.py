"""
Tests for Human Accessibility & Content Negotiation Layer.
Verifies that human operators can access the control deck and documentation
via browser HTML requests while agent-native machine calls receive pure JSON.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers.well_known import get_agent_first_metadata


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_root_content_negotiation_browser_html(client):
    """Browser request with Accept: text/html returns the Human Control Deck HTML."""
    headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9"}
    resp = await client.get("/", headers=headers)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Agent Control Deck" in resp.text
    assert "Trust & Governance Infrastructure" in resp.text


@pytest.mark.anyio
async def test_root_content_negotiation_agent_json(client):
    """Machine/Agent request with Accept: application/json returns API root JSON."""
    headers = {"Accept": "application/json"}
    resp = await client.get("/", headers=headers)
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    data = resp.json()
    assert "agent_first" in data
    assert data["agent_first"]["design_principle"] == "agent_first"


@pytest.mark.anyio
async def test_dashboard_endpoint_returns_html(client):
    """Direct /dashboard route returns 200 OK with dashboard HTML content."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Agent Control Deck" in resp.text
    assert "Receipt Verifier" in resp.text


@pytest.mark.anyio
async def test_agent_first_metadata_declares_human_observability(client):
    """get_agent_first_metadata includes human_observability URLs."""
    meta = get_agent_first_metadata()
    assert "human_observability" in meta
    assert meta["human_observability"]["human_dashboard_url"] == "/dashboard"
    assert meta["human_observability"]["interactive_docs_url"] == "/docs"

    manifest_resp = await client.get("/.well-known/agent.json")
    assert manifest_resp.status_code == 200
    manifest = manifest_resp.json()
    assert manifest["documentation"]["human_dashboard"] == "/dashboard"


@pytest.mark.anyio
async def test_docs_and_llm_txt_remain_accessible(client):
    """OpenAPI and LLM documentation endpoints remain accessible."""
    resp_llm = await client.get("/llm.txt")
    assert resp_llm.status_code == 200
    assert "Agent-Native Middleware API" in resp_llm.text

    resp_openapi = await client.get("/openapi.json")
    assert resp_openapi.status_code == 200
    assert "openapi" in resp_openapi.json()
