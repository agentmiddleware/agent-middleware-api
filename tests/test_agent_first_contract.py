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
