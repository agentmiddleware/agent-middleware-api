"""Phase 5: docs / OpenAPI / discovery honesty for the MCP trust-plane wedge."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services.mcp_generator import McpGenerator


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def proof_surfaces_off(monkeypatch):
    import app.main as main_mod
    import app.routers.discover as discover_mod
    import app.routers.docs as docs_mod
    import app.routers.well_known as well_known_mod

    monkeypatch.setenv("ENABLE_PROOF_SURFACES", "false")
    get_settings.cache_clear()
    cfg = get_settings()
    assert cfg.ENABLE_PROOF_SURFACES is False
    for mod in (main_mod, discover_mod, docs_mod, well_known_mod):
        monkeypatch.setattr(mod, "settings", cfg, raising=False)
    yield
    monkeypatch.setenv("ENABLE_PROOF_SURFACES", "true")
    get_settings.cache_clear()
    restored = get_settings()
    for mod in (main_mod, discover_mod, docs_mod, well_known_mod):
        monkeypatch.setattr(mod, "settings", restored, raising=False)


@pytest.mark.anyio
async def test_tools_json_envelope_is_trust_plane_not_marketplace(client):
    resp = await client.get("/mcp/tools.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == McpGenerator.MANIFEST_NAME
    assert "B2A Service Marketplace" not in body["name"]
    assert "B2A" not in body["name"]
    assert "trust plane" in body["description"].lower()
    assert "executable" in body["description"].lower()
    assert "configured upstream" in body["description"].lower()
    assert "metadata-only" in body["description"].lower()


@pytest.mark.anyio
async def test_discover_pricing_and_guides_are_trust_plane(client, proof_surfaces_off):
    resp = await client.get("/v1/discover")
    assert resp.status_code == 200
    data = resp.json()

    feature_blob = " ".join(
        f for tier in data["pricing"] for f in tier["features"]
    ).lower()
    assert "telemetry" not in feature_blob
    assert "awi" not in feature_blob
    assert "agent messaging" not in feature_blob
    assert "ai decision" not in feature_blob

    guides = data["integration_guides"]
    assert "awi_adoption" not in guides
    assert guides["mcp_server"] == "/mcp"
    assert guides["wedge"] == "/WEDGE.md"
    assert "partner.notes.write" in guides["dogfood"]

    docs = data["documentation"]
    assert docs["wedge"] == "/WEDGE.md"
    assert docs["partner_guide"] == "/DESIGN_PARTNER_GUIDE.md"


@pytest.mark.anyio
async def test_agent_json_documentation_urls_resolve(client, proof_surfaces_off):
    manifest = await client.get("/.well-known/agent.json")
    assert manifest.status_code == 200
    docs = manifest.json()["documentation"]
    assert "agent_recipes" not in docs
    for key in (
        "wedge",
        "security_limitations",
        "partner_guide",
        "llm_readable",
        "llms_readable",
    ):
        path = docs[key]
        resp = await client.get(path)
        assert resp.status_code == 200, f"{key}={path} returned {resp.status_code}"
        assert len(resp.text) > 50


@pytest.mark.anyio
async def test_agent_json_sdk_integrations_are_honest(client):
    """Discovery must not advertise unpublished PyPI/npm package installs."""
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    integrations = resp.json()["integrations"]

    python_sdk = integrations["python_sdk"]
    assert isinstance(python_sdk, dict)
    assert python_sdk["status"] == "release_artifact_only"
    assert python_sdk["version"] == "0.4.0"
    assert python_sdk["install"] == "pip install -e ./b2a_sdk"
    assert "pip install b2a-sdk" not in json.dumps(python_sdk)
    assert "not published" in python_sdk["note"].lower()
    assert "python-sdk-v0.4.0" in python_sdk["note"]

    typescript_sdk = integrations["typescript_sdk"]
    assert isinstance(typescript_sdk, dict)
    assert typescript_sdk["status"] == "not_published"
    assert "npm install @b2a/sdk" not in json.dumps(typescript_sdk)

    assert integrations["preferred_integration"] == "http_mcp"
    assert integrations["mcp"] is True


@pytest.mark.anyio
async def test_llm_txt_does_not_advertise_unpublished_sdk_installs(client):
    resp = await client.get("/llm.txt")
    assert resp.status_code == 200
    text = resp.text
    assert "pip install b2a-sdk" not in text
    assert "npm install @b2a/sdk" not in text
    assert "pip install -e ./b2a_sdk" in text
    assert (
        "not**" in text.lower()
        or "not\npublished" in text.lower()
        or "not published" in text.lower()
    )
    assert "No published TypeScript SDK" in text


@pytest.mark.anyio
async def test_openapi_description_is_trust_plane_not_full_platform(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    description = resp.json()["info"]["description"]
    assert "full agent middleware platform" in description.lower()
    assert "not a full agent middleware platform" in description.lower()
    assert "exactly-once" in description.lower() or "trust plane" in description.lower()


@pytest.mark.anyio
async def test_docs_index_gates_proof_services(client, proof_surfaces_off):
    resp = await client.get("/docs/index")
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_wedge"] == "governed_mcp_trust_plane"
    paths = {s["path"] for s in data["sections"]}
    assert "/WEDGE.md" in paths
    service_ids = {s["id"] for s in data["services"]}
    assert "mcp-trust-plane" in service_ids
    assert "autonomous-pm" not in service_ids
    assert "iot-bridge" not in service_ids


def test_agentmarket_listing_is_wedge_honest():
    text = open("docs/agentmarket-listing.md", encoding="utf-8").read().lower()
    assert "exactly-once" in text
    assert "not a full agent middleware platform" in text
    assert "do **not** list" in text or "do not list" in text
    # Must not pitch AWI/RAG as product capabilities section.
    assert "core capabilities (product)" in text


def test_readme_does_not_claim_deployment_ready_complete():
    text = open("README.md", encoding="utf-8").read().lower()
    assert "not a full agent middleware platform" in text
    assert "deployment-ready for railway" not in text
    assert "tech-debt-remediation-plan.md" in text
