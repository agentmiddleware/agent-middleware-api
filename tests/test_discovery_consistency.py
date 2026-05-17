"""Contract: MCP discovery manifest carries honesty metadata on every tool."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.runtime_mode import SERVICE_NAMES
from app.main import app

_INTEGRATION_STATUSES = frozenset({"simulated", "integrated", "platform"})


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_mcp_tools_json_each_tool_has_honesty_annotations(client):
    resp = await client.get("/mcp/tools.json")
    assert resp.status_code == 200
    data = resp.json()
    tools = data.get("tools") or []
    assert tools, "expected at least one MCP tool"

    for tool in tools:
        ann = tool.get("annotations") or {}
        assert "simulation" in ann
        assert isinstance(ann["simulation"], bool)
        status = ann.get("integrationStatus")
        assert status in _INTEGRATION_STATUSES

        rs = ann.get("runtimeService")
        if status in ("simulated", "integrated"):
            assert rs in SERVICE_NAMES
        if status == "platform":
            assert rs is None


@pytest.mark.anyio
async def test_mcp_tool_simulation_matches_runtime_for_pillars(client):
    """Pillar tools: annotation.simulation matches /health/dependencies for that service."""
    from app.core.runtime_mode import get_simulation_modes

    sim = get_simulation_modes()
    r = await client.get("/mcp/tools.json")
    assert r.status_code == 200
    for tool in r.json()["tools"]:
        ann = tool.get("annotations") or {}
        rs = ann.get("runtimeService")
        if rs in SERVICE_NAMES:
            assert ann.get("simulation") is sim[rs]
