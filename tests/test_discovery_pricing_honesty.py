"""A null pilot price must not read as free in the discovery manifest."""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_discover_pricing_tiers_do_not_advertise_zero_price(client):
    """price_per_credit 0.0 reads as free; pilot tiers carry null instead."""
    resp = await client.get("/v1/discover")
    assert resp.status_code == 200
    tiers = resp.json()["pricing"]
    assert {t["tier_name"] for t in tiers} == {"self_hosted", "design_partner"}
    for tier in tiers:
        assert tier["price_per_credit"] is None, tier
        assert tier["minimum_purchase"] is None, tier


@pytest.mark.anyio
async def test_discover_pricing_states_pilot_terms_are_quoted(client):
    """Some machine reader must find the custom-quote note in the payload."""
    resp = await client.get("/v1/discover")
    assert resp.status_code == 200
    features = [line for tier in resp.json()["pricing"] for line in tier["features"]]
    assert any("writing" in line for line in features), features
