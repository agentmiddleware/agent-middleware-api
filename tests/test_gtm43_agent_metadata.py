"""Regression tests for the gtm-43 agent-metadata slice.

Covers the API-side fixes for the two-manifest confusion, the keyless
bootstrap dead end, and the undated registry decision: the served agent.json
names itself canonical, the served llms.txt says so plus a keyless fallback,
and the registry submission doc carries a dated deferral note.
"""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers.well_known import get_agent_first_metadata

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_agent_first_names_canonical_manifest(client):
    """The API manifest says it is authoritative over the site pointer."""
    meta = get_agent_first_metadata()
    assert "canonical_manifest" in meta
    assert "/.well-known/agent.json" in meta["canonical_manifest"]
    assert "positioning" in meta["canonical_manifest"]

    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    assert (
        resp.json()["agent_first"]["canonical_manifest"] == (meta["canonical_manifest"])
    )


@pytest.mark.anyio
async def test_llms_txt_names_canonical_manifest_and_keyless_fallback(client):
    """llms.txt resolves the two-file confusion and the 401 dead end."""
    resp = await client.get("/llms.txt")
    assert resp.status_code == 200
    text = resp.text
    assert "canonical" in text
    assert "agent_first.positioning" in text
    assert "/health/dependencies" in text
    assert "/.well-known/trust-keys.json" in text
    assert "/openapi.json" in text


def test_registry_submission_carries_dated_deferral_note():
    """The registry doc states the deferral decision with a date."""
    doc = (ROOT / "docs" / "mcp-registry-submission.md").read_text(encoding="utf-8")
    assert "Decision status" in doc
    assert "2026-10-08" in doc
    assert "deferred" in doc
    assert "deploy-railway.md#required-production-variables" in doc
