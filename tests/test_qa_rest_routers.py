"""QA pass over rest routers: quotes, me, api-keys logs.

Covers behavior the existing suite does not:

- quotes for persistently registered tools (existing quote tests only use
  local tools), including a stored row whose category is outside the enum
  (a 500 before the fix, a 400 after) and a stored negative price (400).
- every /v1/me endpoint refuses a bootstrap admin key with
  wallet_key_required (the existing test covers only three paths).
- /v1/me pagination with an offset past the total is empty and closed.
- GET /v1/api-keys/{wallet}/logs validates its limit like every other
  list endpoint (negative or zero is 422, not a silent unlimited read).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import ServiceRegistryModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _register_persistent(owner_wallet_id: str, **overrides) -> dict:
    registry = get_service_registry()
    params = {
        "name": "QA Persistent Tool",
        "description": "persistent-path quote coverage",
        "category": ServiceCategory.AGENT_COMMS,
        "credits_per_unit": 7.5,
        "owner_wallet_id": owner_wallet_id,
    }
    params.update(overrides)
    return await registry.register_persistent(**params)


async def _insert_registry_row(
    service_id: str, owner_wallet_id: str, category: str, price: str
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ServiceRegistryModel(
                service_id=service_id,
                name="QA legacy row",
                description="row predating the category enum",
                owner_wallet_id=owner_wallet_id,
                category=category,
                credits_per_unit=Decimal(price),
                unit_name="call",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_quote_for_persistent_tool_uses_stored_price(client, clean_database):
    """A persistently registered tool quotes at its stored price."""
    agent = await provision_agent_wallet(client)
    tool = await _register_persistent(agent["agent_wallet_id"])

    resp = await client.post(
        "/v1/quotes",
        json={"wallet_id": agent["agent_wallet_id"], "tool": tool["service_id"]},
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(str(resp.json()["quoted_credits"])) == Decimal("7.5")


@pytest.mark.asyncio
async def test_quote_for_tool_with_unknown_category_is_400_not_500(
    client, clean_database
):
    """A registry row with a category outside the enum is a bad tool record.

    The quote endpoint must answer 400 tool_price_invalid: the row is a
    promise no charge could honor. Before the fix the bare enum coercion
    raised through as a 500.
    """
    agent = await provision_agent_wallet(client)
    await _insert_registry_row(
        "svc-qa-unknown-cat",
        agent["agent_wallet_id"],
        "telegraph_operator",
        "3.0",
    )

    resp = await client.post(
        "/v1/quotes",
        json={"wallet_id": agent["agent_wallet_id"], "tool": "svc-qa-unknown-cat"},
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "tool_price_invalid"


@pytest.mark.asyncio
async def test_quote_for_tool_with_negative_stored_price_is_400(client, clean_database):
    """A stored negative price is never signed into a quote."""
    agent = await provision_agent_wallet(client)
    await _insert_registry_row(
        "svc-qa-negative-price",
        agent["agent_wallet_id"],
        ServiceCategory.AGENT_COMMS.value,
        "-2.0",
    )

    resp = await client.post(
        "/v1/quotes",
        json={
            "wallet_id": agent["agent_wallet_id"],
            "tool": "svc-qa-negative-price",
        },
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "tool_price_invalid"


@pytest.mark.asyncio
async def test_bootstrap_key_rejected_on_every_me_endpoint(client, clean_database):
    """All /v1/me reads need a wallet key, including alerts and authority."""
    await provision_agent_wallet(client)
    paths = (
        "/v1/me/alerts",
        "/v1/me/authority",
        "/v1/me/permits",
        "/v1/me/permit-requests",
        "/v1/me/quotes",
        "/v1/me/receipts",
        "/v1/me/audit/events",
    )
    for path in paths:
        response = await client.get(path, headers=BOOTSTRAP_HEADERS)
        assert response.status_code == 403, path
        assert response.json()["detail"]["error"] == "wallet_key_required", path


@pytest.mark.asyncio
async def test_me_list_with_offset_past_total_is_empty_and_closed(
    client, clean_database
):
    """Paging past the end returns no rows and no further page."""
    agent = await provision_agent_wallet(client)
    resp = await client.get(
        "/v1/me/quotes",
        params={"limit": 50, "offset": 100},
        headers=agent["agent_headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["quotes"] == []
    assert body["has_more"] is False
    assert body["next_offset"] is None


@pytest.mark.asyncio
async def test_rotation_logs_rejects_non_positive_limit(client, clean_database):
    """The logs list validates its limit like every other list endpoint."""
    agent = await provision_agent_wallet(client)
    url = f"/v1/api-keys/{agent['agent_wallet_id']}/logs"
    for bad in (-1, 0):
        resp = await client.get(
            url, params={"limit": bad}, headers=agent["agent_headers"]
        )
        assert resp.status_code == 422, (bad, resp.text)

    ok = await client.get(url, params={"limit": 50}, headers=agent["agent_headers"])
    assert ok.status_code == 200, ok.text
    assert ok.json() == []
