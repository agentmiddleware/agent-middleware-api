"""wallet.status and child spend caps must be authoritative across the money
layer, not only inside charge().

Regression coverage for the finding that a frozen wallet kept spending and
could drain via transfer or spawn a fresh unfrozen child, and that a capped
child escaped its cap through transfer or child-spawn.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import WalletModel
from app.main import app

BOOTSTRAP = {"X-API-Key": "test-key"}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_agent(client, *, budget=5000, initial=10000) -> tuple[str, str]:
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "S", "email": "s@t.com", "initial_credits": initial},
        headers=BOOTSTRAP,
    )
    spn = sponsor.json()["wallet_id"]
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": spn, "agent_id": "bot", "budget_credits": budget},
        headers=BOOTSTRAP,
    )
    return spn, agent.json()["wallet_id"]


async def _set_status(wallet_id: str, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.execute(
            select(WalletModel).where(WalletModel.wallet_id == wallet_id)
        )
        wallet = row.scalar_one()
        wallet.status = status
        session.add(wallet)
        await session.commit()


@pytest.mark.anyio
async def test_frozen_wallet_cannot_charge(client, clean_database):
    _, agent = await _make_agent(client)
    await _set_status(agent, "frozen")

    resp = await client.post(
        f"/v1/billing/charge?wallet_id={agent}&service=iot_bridge&units=1",
        headers=BOOTSTRAP,
    )
    assert resp.status_code == 402


@pytest.mark.anyio
async def test_frozen_wallet_cannot_transfer_out(client, clean_database):
    _, agent = await _make_agent(client)
    _, other = await _make_agent(client)
    await _set_status(agent, "frozen")

    resp = await client.post(
        f"/v1/billing/transfer?from_wallet_id={agent}&to_wallet_id={other}&amount=10",
        headers=BOOTSTRAP,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "transfer_error"


@pytest.mark.anyio
async def test_frozen_wallet_cannot_spawn_child(client, clean_database):
    _, agent = await _make_agent(client)
    await _set_status(agent, "frozen")

    resp = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": agent,
            "child_agent_id": "sub",
            "budget_credits": 10,
            "max_spend": 10,
        },
        headers=BOOTSTRAP,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "child_wallet_error"


@pytest.mark.anyio
async def test_frozen_sponsor_cannot_provision_agent_with_positive_balance(
    client, clean_database
):
    sponsor, _ = await _make_agent(client, budget=5000, initial=10000)
    await _set_status(sponsor, "frozen")

    response = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor,
            "agent_id": "blocked-after-freeze",
            "budget_credits": 1000,
        },
        headers=BOOTSTRAP,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "wallet_error"
    assert "frozen" in response.json()["detail"]["message"]
    sponsor_response = await client.get(
        f"/v1/billing/wallets/{sponsor}", headers=BOOTSTRAP
    )
    assert sponsor_response.json()["balance"] == 5000
    assert sponsor_response.json()["status"] == "frozen"


@pytest.mark.anyio
async def test_child_cap_enforced_on_transfer(client, clean_database):
    _, agent = await _make_agent(client)
    _, sink = await _make_agent(client)

    child_resp = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": agent,
            "child_agent_id": "capped",
            "budget_credits": 100,
            "max_spend": 5,
        },
        headers=BOOTSTRAP,
    )
    assert child_resp.status_code == 201
    child = child_resp.json()["wallet_id"]

    # The child holds 100 credits but is capped at 5 lifetime spend. Moving 10
    # out would exceed the cap and must be rejected, closing the transfer-escape.
    resp = await client.post(
        f"/v1/billing/transfer?from_wallet_id={child}&to_wallet_id={sink}&amount=10",
        headers=BOOTSTRAP,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "transfer_error"


@pytest.mark.anyio
async def test_child_cap_enforced_when_spawning_grandchild(client, clean_database):
    _, agent = await _make_agent(client)
    child_resp = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": agent,
            "child_agent_id": "capped-parent",
            "budget_credits": 100,
            "max_spend": 5,
        },
        headers=BOOTSTRAP,
    )
    assert child_resp.status_code == 201
    child = child_resp.json()["wallet_id"]

    response = await client.post(
        "/v1/billing/wallets/child",
        json={
            "parent_wallet_id": child,
            "child_agent_id": "cap-escape",
            "budget_credits": 10,
            "max_spend": 10,
        },
        headers=BOOTSTRAP,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "child_wallet_error"


@pytest.mark.anyio
async def test_active_wallet_still_operates(client, clean_database):
    """The enforcement must not block a normal active wallet."""
    _, agent = await _make_agent(client)
    resp = await client.post(
        f"/v1/billing/charge?wallet_id={agent}&service=iot_bridge&units=1",
        headers=BOOTSTRAP,
    )
    assert resp.status_code == 200
