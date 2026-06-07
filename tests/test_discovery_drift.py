import json
import os
import subprocess
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import mcp_phase9_tools
from app.services.mcp_phase9_tools import MCP_PHASE9_TOOLS
from app.services.service_registry import get_service_registry


_DEFAULT_MCP_TOOL_IDS = {
    "data-indexer",
    "content-generator",
    "telemetry-processor",
    "semantic-search",
}


def _clear_builtin_mcp_tools_for_lazy_start():
    registry = get_service_registry()
    for tool in MCP_PHASE9_TOOLS:
        registry.unregister_local(tool["service_id"])
    for tool_id in _DEFAULT_MCP_TOOL_IDS:
        registry.unregister_local(tool_id)
    mcp_phase9_tools._registered = False
    mcp_phase9_tools._default_services_registered = False


def _assert_phase9_tool_available(tools):
    assert {tool["name"] for tool in tools} >= {"awi_passkey_challenge"}


def _tools_by_name(tools):
    return {tool["name"]: tool for tool in tools}


def _without_generated_at(manifest):
    return {key: value for key, value in manifest.items() if key != "generated_at"}


_SURFACE_PAYLOAD_SCRIPT = """
import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
payload = {
    "agent": client.get("/.well-known/agent.json").json(),
    "discover": client.get("/v1/discover").json(),
    "root": client.get("/").json(),
    "openapi_paths": sorted(client.get("/openapi.json").json()["paths"]),
}
print(json.dumps(payload))
"""


def _surface_payload(mode: str) -> dict:
    env = os.environ.copy()
    env["API_SURFACE_MODE"] = mode
    env.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    env.setdefault("VALID_API_KEYS", "test-key")
    result = subprocess.run(
        [sys.executable, "-c", _SURFACE_PAYLOAD_SCRIPT],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_agent_manifest_points_to_canonical_control_plane_surfaces(client):
    response = await client.get("/.well-known/agent.json")

    assert response.status_code == 200
    data = response.json()
    endpoints = data["endpoints"]
    agent_first = data["agent_first"]

    assert endpoints["billing"] == "/v1/billing"
    assert endpoints["mcp"] == "/mcp"
    assert endpoints["health"] == "/health"
    assert endpoints["agent_manifest"] == "/.well-known/agent.json"
    assert endpoints["llm_docs"] == "/llm.txt"
    assert "/mcp/tools.json" in agent_first["bootstrap_sequence"]
    assert agent_first["simulation_and_dependency_truth"] == "/health/dependencies"


@pytest.mark.anyio
async def test_discover_and_agent_manifest_share_agent_first_contract(client):
    agent_response = await client.get("/.well-known/agent.json")
    discover_response = await client.get("/v1/discover")

    assert agent_response.status_code == 200
    assert discover_response.status_code == 200
    assert (
        agent_response.json()["agent_first"] == discover_response.json()["agent_first"]
    )


def test_trust_plane_discovery_does_not_advertise_proof_surfaces():
    payload = _surface_payload("trust_plane")

    agent = payload["agent"]
    discover = payload["discover"]
    root = payload["root"]
    openapi_paths = set(payload["openapi_paths"])

    assert "/.well-known/awi.json" not in agent["agent_first"]["bootstrap_sequence"]
    assert "awi" not in agent["endpoints"]
    assert "telemetry" not in agent["endpoints"]
    assert "ai" not in agent["endpoints"]
    assert "awi_automation" not in agent["capabilities"]
    assert "passkey_auth" not in agent["capabilities"]

    proof_services = {
        "iot_bridge",
        "autonomous_pm",
        "media_engine",
        "agent_comms",
        "content_factory",
        "agent_oracle",
        "red_team_security",
        "rtaas",
        "sandbox",
        "awi_phase9",
        "telemetry_scope",
    }
    assert set(root["services"]).isdisjoint(proof_services)
    assert root["api_surface"]["mode"] == "trust_plane"

    proof_capabilities = {
        "awi",
        "telemetry",
        "sandbox",
        "iot",
        "passkey",
        "dom_bridge",
        "rag_memory",
    }
    assert {capability["name"] for capability in discover["capabilities"]}.isdisjoint(
        proof_capabilities
    )
    assert discover["awi_endpoints"] == []
    assert "awi_adoption" not in discover["integration_guides"]

    proof_paths = {
        "/.well-known/awi.json",
        "/v1/awi/sessions",
        "/v1/telemetry/events",
        "/v1/sandbox/environments",
        "/v1/oracle/crawl",
        "/v1/content/generate",
    }
    assert openapi_paths.isdisjoint(proof_paths)


def test_full_mode_discovery_preserves_proof_surfaces():
    payload = _surface_payload("full")

    assert (
        "/.well-known/awi.json" in payload["agent"]["agent_first"]["bootstrap_sequence"]
    )
    assert "awi" in payload["agent"]["endpoints"]
    assert "passkey_auth" in payload["agent"]["capabilities"]
    assert "iot_bridge" in payload["root"]["services"]
    assert payload["root"]["api_surface"]["mode"] == "full"
    assert payload["discover"]["awi_endpoints"]
    assert "awi_adoption" in payload["discover"]["integration_guides"]
    assert "/.well-known/awi.json" in payload["openapi_paths"]


@pytest.mark.anyio
async def test_openapi_contains_core_control_plane_routes(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/mcp/messages" in paths
    assert "/mcp/tools/{service_id}/invoke" in paths
    assert "/v1/billing/charge" in paths
    assert "/v1/audit/events" in paths
    assert "/v1/planner/optimize" in paths


@pytest.mark.anyio
async def test_mcp_manifest_tools_include_pricing_and_simulation_truth(client):
    response = await client.get("/mcp/tools.json")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert tools
    for tool in tools:
        annotations = tool["annotations"]
        assert "creditsPerCall" in annotations
        assert "unitName" in annotations
        assert "simulation" in annotations
        assert "integrationStatus" in annotations


@pytest.mark.anyio
async def test_well_known_mcp_manifest_matches_canonical_mcp_manifest(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    well_known_response = await client.get("/.well-known/mcp/tools.json")
    canonical_response = await client.get("/mcp/tools.json")

    assert well_known_response.status_code == 200
    assert canonical_response.status_code == 200
    well_known = well_known_response.json()
    canonical = canonical_response.json()

    assert _without_generated_at(well_known) == _without_generated_at(canonical)

    well_known_tools = _tools_by_name(well_known["tools"])
    assert "awi_passkey_challenge" in well_known_tools

    annotations = well_known_tools["awi_passkey_challenge"]["annotations"]
    assert annotations["creditsPerCall"] == 1.0
    assert annotations["unitName"] == "challenge"
    assert annotations["category"] == "agent_comms"
    assert annotations["simulation"] is True
    assert annotations["integrationStatus"] == "simulated"
    assert annotations["runtimeService"] == "agent_comms"


@pytest.mark.anyio
async def test_prefixed_well_known_mcp_manifest_is_not_a_discovery_route(client):
    response = await client.get("/mcp/.well-known/mcp/tools.json")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_mcp_tools_endpoint_lazily_registers_local_tools(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    response = await client.get("/mcp/tools")

    assert response.status_code == 200
    _assert_phase9_tool_available(response.json()["tools"])


@pytest.mark.anyio
async def test_mcp_messages_tools_list_lazily_registers_local_tools(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    response = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": "lazy-list",
            "method": "tools/list",
            "params": {},
        },
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "lazy-list"
    _assert_phase9_tool_available(payload["result"]["tools"])


@pytest.mark.anyio
async def test_mcp_get_tool_lazily_registers_local_tools(client):
    _clear_builtin_mcp_tools_for_lazy_start()

    response = await client.get("/mcp/tools/awi_passkey_challenge")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "awi_passkey_challenge"
    assert data["annotations"]["creditsPerCall"] == 1.0
