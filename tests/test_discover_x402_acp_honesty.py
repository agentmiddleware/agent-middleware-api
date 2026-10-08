"""
Test that /v1/discover honestly advertises the dormant x402 and ACP surfaces.

Both routers mount only with ENABLE_PROOF_SURFACES=true (x402 directly, ACP
via billing.expansion_router), and ACP checkout additionally needs a Stripe
key to charge through. Discovery must therefore:

- omit both capabilities when proof surfaces are off (routes answer 404);
- list x402 whenever proof surfaces are on (no Stripe needed);
- list acp only when proof surfaces are on AND Stripe is configured;
- describe both as facilitation/evidence only, never as money movement.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _capability_names(data):
    return {cap["name"] for cap in data["capabilities"]}


def _set_flag(monkeypatch, *, proof_surfaces, stripe_key=None):
    import app.routers.discover as discover_mod

    if stripe_key is not None:
        monkeypatch.setenv("STRIPE_SECRET_KEY", stripe_key)
    get_settings.cache_clear()
    cfg = get_settings()
    cfg.ENABLE_PROOF_SURFACES = proof_surfaces
    monkeypatch.setattr(discover_mod, "settings", cfg, raising=False)
    return cfg


@pytest.mark.anyio
async def test_discover_omits_x402_and_acp_when_proof_surfaces_off(client, monkeypatch):
    """Flag off means both routers are unmounted, so neither may be listed."""
    _set_flag(
        monkeypatch,
        proof_surfaces=False,
        stripe_key="sk_test_fake_key_for_testing",
    )
    try:
        resp = await client.get("/v1/discover")
        assert resp.status_code == 200
        names = _capability_names(resp.json())
        assert "x402" not in names
        assert "acp" not in names
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discover_lists_x402_without_stripe_when_flag_on(client, monkeypatch):
    """x402 needs no Stripe key: flag on alone must advertise it."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    _set_flag(monkeypatch, proof_surfaces=True)
    try:
        resp = await client.get("/v1/discover")
        assert resp.status_code == 200
        by_name = {cap["name"]: cap for cap in resp.json()["capabilities"]}
        assert "x402" in by_name
        description = by_name["x402"]["description"].lower()
        assert "does not execute" in description
        assert "permit" in description
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discover_omits_acp_without_stripe_when_flag_on(client, monkeypatch):
    """ACP checkout charges through Stripe, so without a key it must stay out."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    _set_flag(monkeypatch, proof_surfaces=True)
    try:
        resp = await client.get("/v1/discover")
        assert resp.status_code == 200
        assert "acp" not in _capability_names(resp.json())
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discover_lists_acp_with_stripe_when_flag_on(client, monkeypatch):
    """Flag on plus Stripe configured: ACP is reachable, so list it honestly."""
    _set_flag(
        monkeypatch,
        proof_surfaces=True,
        stripe_key="sk_test_fake_key_for_testing",
    )
    try:
        resp = await client.get("/v1/discover")
        assert resp.status_code == 200
        by_name = {cap["name"]: cap for cap in resp.json()["capabilities"]}
        assert "acp" in by_name
        description = by_name["acp"]["description"].lower()
        assert "stripe" in description
        assert "no credits" in description or "never mints" in description
    finally:
        get_settings.cache_clear()
