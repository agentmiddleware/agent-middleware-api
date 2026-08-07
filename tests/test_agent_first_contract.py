"""
Contract tests for agent-first discovery: bootstrap URLs must stay public and
aligned with get_agent_first_metadata() so autonomous clients do not drift.
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
async def test_bootstrap_sequence_urls_are_public_ok(client):
    meta = get_agent_first_metadata()
    for path in meta["bootstrap_sequence"]:
        resp = await client.get(path)
        assert resp.status_code == 200, f"bootstrap path not OK: {path}"


@pytest.mark.anyio
async def test_simulation_truth_endpoint_has_simulation_modes(client):
    path = get_agent_first_metadata()["simulation_and_dependency_truth"]
    resp = await client.get(path)
    assert resp.status_code == 200
    data = resp.json()
    assert "simulation_modes" in data
    assert "enable_proof_surfaces" in data


@pytest.mark.anyio
async def test_agent_first_declares_product_wedge(client):
    meta = get_agent_first_metadata()
    assert meta["product_wedge"] == "governed_mcp_trust_plane"
    assert meta["product_loop"][0] == "discover"
    assert "receipt" in meta["product_loop"]
    assert "proof_surface_note" in meta
    resp = await client.get("/.well-known/agent.json")
    assert resp.json()["agent_first"] == meta


@pytest.mark.anyio
async def test_agent_manifest_offers_honest_credential_free_local_proof(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()

    trial = data["try_it"]
    assert trial["mode"] == "local_self_hosted"
    assert trial["command"] == "make prove-trust-plane"
    assert trial["requires_live_credentials"] is False
    assert trial["live_access"] == "operator_issued"
    assert "signed_receipt" in trial["proves"]
    assert "replay_without_second_charge" in trial["proves"]
    assert data["authentication"]["public_self_serve"] is False
