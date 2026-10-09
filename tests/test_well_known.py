"""Focused coverage for app/routers/well_known.py discovery endpoints."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import well_known
from app.services.signing_keys import SigningKeyError

RAW_KEY = bytes(range(32))
PUBLIC_B64 = base64.b64encode(RAW_KEY).decode()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _fake_service(monkeypatch, keys=None, error=None):
    class _Fake:
        async def list_public_keys(self):
            if error is not None:
                raise error
            return list(keys or [])

    monkeypatch.setattr(well_known, "get_signing_key_service", lambda: _Fake())


def _fake_key(**overrides):
    values = {
        "key_id": "test-kid-1",
        "alg": "Ed25519",
        "public_key_b64": PUBLIC_B64,
        "status": "active",
        "created_at": None,
        "activated_at": None,
        "retired_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.anyio
async def test_agent_json_returns_bootstrap_manifest(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    data = resp.json()
    assert data["name"] == "agent-middleware-api"
    assert "receipts" in data["capabilities"]
    assert "permits" in data["capabilities"]
    assert data["endpoints"]["trust_keys"] == "/.well-known/trust-keys.json"
    assert data["endpoints"]["agent_manifest"] == "/.well-known/agent.json"
    assert data["agent_first"]["primary_audience"] == "autonomous_agents"


@pytest.mark.anyio
async def test_agent_json_hides_proof_surfaces_by_default(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proof_surfaces"] == []
    assert "awi_manifest" not in data["endpoints"]


@pytest.mark.anyio
async def test_agent_json_includes_proof_surfaces_when_enabled(client):
    from app.core.config import get_settings

    cfg = get_settings()
    previous = cfg.ENABLE_PROOF_SURFACES
    cfg.ENABLE_PROOF_SURFACES = True
    try:
        resp = await client.get("/.well-known/agent.json")
    finally:
        cfg.ENABLE_PROOF_SURFACES = previous
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["proof_surfaces"]) > 0
    assert data["endpoints"]["awi_manifest"] == "/.well-known/awi.json"


@pytest.mark.anyio
async def test_awi_json_unmounted_returns_404(client):
    from app.core.config import get_settings

    cfg = get_settings()
    previous = cfg.ENABLE_PROOF_SURFACES
    cfg.ENABLE_PROOF_SURFACES = False
    try:
        resp = await client.get("/.well-known/awi.json")
    finally:
        cfg.ENABLE_PROOF_SURFACES = previous
    assert resp.status_code == 404
    assert resp.json()["error"] == "awi_manifest_unmounted"


@pytest.mark.anyio
async def test_awi_json_mounted_returns_proof_surface_manifest(client):
    from app.core.config import get_settings

    cfg = get_settings()
    previous = cfg.ENABLE_PROOF_SURFACES
    cfg.ENABLE_PROOF_SURFACES = True
    try:
        resp = await client.get("/.well-known/awi.json")
    finally:
        cfg.ENABLE_PROOF_SURFACES = previous
    assert resp.status_code == 200
    data = resp.json()
    assert data["surface"] == "proof_surface"
    assert isinstance(data["actions"], list)
    assert len(data["representation_types"]) > 0
    assert "X-Permit-Id" in data["http_authorization"]["required_headers"]


@pytest.mark.anyio
async def test_trust_keys_empty_returns_503(client, monkeypatch):
    _fake_service(monkeypatch, keys=[])
    resp = await client.get("/.well-known/trust-keys.json")
    assert resp.status_code == 503
    assert resp.json()["error"] == "trust_keys_unavailable"


@pytest.mark.anyio
async def test_trust_keys_service_error_returns_503(client, monkeypatch):
    _fake_service(monkeypatch, error=SigningKeyError("store down"))
    resp = await client.get("/.well-known/trust-keys.json")
    assert resp.status_code == 503
    assert resp.json()["error"] == "trust_keys_unavailable"


@pytest.mark.anyio
async def test_trust_keys_publishes_key_with_jwk(client, monkeypatch):
    from app.core.config import public_api_origin

    _fake_service(monkeypatch, keys=[_fake_key()])
    resp = await client.get("/.well-known/trust-keys.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alg"] == "Ed25519"
    assert data["issuer"] == public_api_origin()
    assert len(data["keys"]) == 1
    entry = data["keys"][0]
    assert entry["kid"] == "test-kid-1"
    assert entry["jwk"]["kty"] == "OKP"
    assert entry["jwk"]["crv"] == "Ed25519"


@pytest.mark.anyio
async def test_jwks_empty_returns_503(client, monkeypatch):
    _fake_service(monkeypatch, keys=[])
    resp = await client.get("/.well-known/jwks.json")
    assert resp.status_code == 503
    assert resp.json()["error"] == "trust_keys_unavailable"


@pytest.mark.anyio
async def test_jwks_publishes_key_set(client, monkeypatch):
    _fake_service(monkeypatch, keys=[_fake_key()])
    resp = await client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    assert "jwk-set+json" in resp.headers["content-type"]
    data = resp.json()
    assert len(data["keys"]) == 1
    assert data["keys"][0]["kid"] == "test-kid-1"


def test_b64_to_b64url_rejects_invalid_input():
    assert well_known._b64_to_b64url("!!!not-base64!!!") is None


def test_published_key_omits_jwk_for_non_ed25519():
    entry = well_known._published_key(_fake_key(alg="RS256"))
    assert entry["kid"] == "test-kid-1"
    assert "jwk" not in entry


@pytest.mark.anyio
async def test_mcp_tools_mirror_is_reachable_locally(client):
    resp = await client.get("/.well-known/mcp/tools.json")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
