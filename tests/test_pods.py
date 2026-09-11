"""Tests for pods: a named group of agent API keys under one shared budget.

Marked `dormant` (see tests/conftest.py DORMANT_SURFACE_TEST_MODULES) so the
pods router is mounted without flipping ENABLE_PROOF_SURFACES globally,
mirroring how production would mount it for a specific pilot.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


ADMIN_HEADERS = {"X-API-Key": "test-key"}


async def _create_pod(client, **overrides):
    payload = {
        "pod_name": "research",
        "budget_credits": 1000.0,
        "members": [
            {"agent_id": "researcher-1", "key_name": "researcher-1-key"},
            {"agent_id": "researcher-2", "key_name": "researcher-2-key"},
        ],
    }
    payload.update(overrides)
    return await client.post("/v1/pods", json=payload, headers=ADMIN_HEADERS)


@pytest.mark.anyio
async def test_create_pod_provisions_shared_budget_and_member_keys(client):
    """One call creates a shared-budget wallet plus one wallet+key per member."""
    resp = await _create_pod(client)
    assert resp.status_code == 201
    data = resp.json()

    assert data["pod_name"] == "research"
    assert data["budget_credits"] == 1000.0
    assert data["pod_id"].startswith("spn-")

    members = data["members"]
    assert len(members) == 2
    agent_ids = {m["agent_id"] for m in members}
    assert agent_ids == {"researcher-1", "researcher-2"}
    for member in members:
        # Even split of 1000 across 2 members with no explicit share.
        assert member["budget_credits"] == 500.0
        assert member["wallet_id"]
        assert member["key_id"]
        assert member["api_key"]  # shown once, here
        assert member["api_key"].startswith(member["key_prefix"])


@pytest.mark.anyio
async def test_pod_member_keys_are_independently_usable(client):
    """Each provisioned member key authenticates and reads its own wallet."""
    resp = await _create_pod(client)
    member = resp.json()["members"][0]

    me = await client.get(
        "/v1/me/authority", headers={"X-API-Key": member["api_key"]}
    )
    assert me.status_code == 200
    assert me.json()["wallet_id"] == member["wallet_id"]


@pytest.mark.anyio
async def test_explicit_member_budgets_are_honored(client):
    resp = await _create_pod(
        client,
        budget_credits=1000.0,
        members=[
            {"agent_id": "lead", "key_name": "lead-key", "budget_credits": 700.0},
            {"agent_id": "assistant", "key_name": "assistant-key"},
        ],
    )
    assert resp.status_code == 201
    members = {m["agent_id"]: m for m in resp.json()["members"]}
    assert members["lead"]["budget_credits"] == 700.0
    # Remainder (300) goes entirely to the one unset member.
    assert members["assistant"]["budget_credits"] == 300.0


@pytest.mark.anyio
async def test_even_split_never_over_allocates_past_the_pod_total(client):
    """A remainder that doesn't divide evenly must truncate, not round up.

    Regression for a real bug (flagged by review on PetrefiedThunder/
    agent-middleware-api#429): 1 / 6 = 0.16666666...repeating. Decimal's
    default quantize rounding (ROUND_HALF_EVEN) rounds the 8th decimal
    place up to 0.16666667 here, and 6 members at that share sum to
    1.00000002 - over the pod's total budget. That drained the sponsor
    wallet before the last member's create_agent_wallet call, which then
    failed with InsufficientFundsError and turned a clean pod creation
    into a partial-provisioning 500. Truncating (ROUND_DOWN) instead
    guarantees the per-member shares can never sum past the total.
    """
    resp = await _create_pod(
        client,
        pod_name="remainder-pod",
        budget_credits=1.0,
        members=[{"agent_id": f"m{i}"} for i in range(6)],
    )
    assert resp.status_code == 201
    data = resp.json()

    members = data["members"]
    assert len(members) == 6
    total_allocated = sum(m["budget_credits"] for m in members)
    assert total_allocated <= 1.0
    # Every member still gets a real, usable share, not zero.
    assert all(m["budget_credits"] > 0 for m in members)


@pytest.mark.anyio
async def test_over_allocated_member_budgets_fail_before_creating_anything(client):
    """Requesting more than the pod total is rejected, and nothing is created."""
    resp = await _create_pod(
        client,
        budget_credits=100.0,
        members=[
            {"agent_id": "over-1", "budget_credits": 60.0},
            {"agent_id": "over-2", "budget_credits": 60.0},
        ],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "pod_budget_exceeded"

    # Neither member's key ever got created: no key for over-1 exists to
    # authenticate with, and the pod itself never shows up (nothing to GET).
    # We can't ask "does a wallet named over-1 exist" without a lookup route,
    # so instead assert indirectly: creating a *valid* pod with the same
    # member ids afterward must succeed, which would fail on a uniqueness
    # constraint if the first (rejected) request had partially persisted.
    retry = await _create_pod(
        client,
        pod_name="research-retry",
        budget_credits=100.0,
        members=[{"agent_id": "over-1"}, {"agent_id": "over-2"}],
    )
    assert retry.status_code == 201


@pytest.mark.anyio
async def test_create_pod_requires_bootstrap_admin(client):
    resp = await _create_pod(client)
    admin_pod_id = resp.json()["pod_id"] if resp.status_code == 201 else None

    non_admin = await client.post(
        "/v1/pods",
        json={
            "pod_name": "shadow-pod",
            "budget_credits": 100.0,
            "members": [{"agent_id": "intruder"}],
        },
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert non_admin.status_code in (401, 403)

    if admin_pod_id:
        get_resp = await client.get(
            f"/v1/pods/{admin_pod_id}",
            headers={"X-API-Key": "not-a-real-key"},
        )
        assert get_resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_get_pod_budget_reflects_allocation(client):
    resp = await _create_pod(client, budget_credits=1000.0)
    pod_id = resp.json()["pod_id"]

    budget = await client.get(f"/v1/pods/{pod_id}", headers=ADMIN_HEADERS)
    assert budget.status_code == 200
    data = budget.json()
    assert data["pod_id"] == pod_id
    assert data["pod_name"] == "research"
    assert data["total_budget"] == 1000.0
    assert data["allocated_to_members"] == 1000.0  # both members, evenly split
    assert data["remaining_at_pod"] == 0.0
    assert len(data["members"]) == 2
    for m in data["members"]:
        assert m["balance"] == 500.0
        assert "api_key" not in m  # never leaked from the budget view


@pytest.mark.anyio
async def test_get_pod_budget_404_for_unknown_pod(client):
    resp = await client.get("/v1/pods/spn-does-not-exist", headers=ADMIN_HEADERS)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "pod_not_found"


@pytest.mark.anyio
async def test_get_pod_budget_404_for_non_pod_sponsor_wallet(client):
    """An ordinary sponsor wallet (no pod metadata) is not addressable as a pod."""
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Ordinary Sponsor",
            "email": "sponsor@test.com",
            "initial_credits": 100.0,
        },
        headers=ADMIN_HEADERS,
    )
    assert sponsor.status_code == 201
    sponsor_id = sponsor.json()["wallet_id"]

    resp = await client.get(f"/v1/pods/{sponsor_id}", headers=ADMIN_HEADERS)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_a_pod"


@pytest.mark.anyio
async def test_duplicate_member_agent_ids_rejected(client):
    resp = await _create_pod(
        client,
        members=[{"agent_id": "dup"}, {"agent_id": "dup"}],
    )
    assert resp.status_code == 422


def test_pods_router_is_registered_as_dormant():
    """Pods is a dormant trust surface, not a core one.

    AGENTS.md: no new core capability without documented named-customer
    evidence. This asserts the classification directly rather than trying
    to prove non-mounting at runtime (the shared test app process mounts
    dormant routers once a `dormant`-marked test in the session needs them
    and never unmounts, so a live 404 check here would be order-dependent).
    Production correctness — ENABLE_PROOF_SURFACES=false means /v1/pods is
    never mounted or advertised — is app.main's own responsibility and is
    covered by the shared dormant/core route-set tests, not duplicated here.
    """
    from app.main import CORE_TRUST_ROUTERS, DORMANT_TRUST_ROUTERS
    from app.routers import pods as pods_router_module

    assert pods_router_module in DORMANT_TRUST_ROUTERS
    assert pods_router_module not in CORE_TRUST_ROUTERS
