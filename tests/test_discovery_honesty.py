"""Discovery honesty: product wedge vs labeled proof surfaces."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers.well_known import PRODUCT_CAPABILITIES, _build_agent_manifest


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_agent_json_product_capabilities_are_trust_plane_only(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["capabilities"] == PRODUCT_CAPABILITIES
    assert all(entry["status"] == "proof_surface" for entry in data["proof_surfaces"])


@pytest.mark.anyio
async def test_discover_labels_proof_surfaces(client):
    resp = await client.get("/v1/discover")
    assert resp.status_code == 200
    data = resp.json()
    by_name = {c["name"]: c for c in data["capabilities"]}
    assert by_name["mcp"]["surface"] == "product"
    assert by_name["permits"]["surface"] == "product"
    assert by_name["awi"]["surface"] == "proof_surface"
    assert by_name["passkey"]["simulation_default"] is True


@pytest.mark.anyio
async def test_awi_manifest_declares_proof_surface(client):
    resp = await client.get("/.well-known/awi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["surface"] == "proof_surface"
    limitations = " ".join(data["known_limitations"]).lower()
    assert "proof surface" in limitations or "permit" in limitations


def test_manifest_builder_matches_live_endpoint_shape():
    built = _build_agent_manifest().model_dump(mode="json")
    assert built["capabilities"] == PRODUCT_CAPABILITIES
    assert "permits" in built["endpoints"]
    assert built["agent_first"]["product_wedge"] == "governed_mcp_trust_plane"
