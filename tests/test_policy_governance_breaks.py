"""Break-it regression tests for wallet policy bundles and governance.

Each test below pins a real break found by adversarial probing: malformed
patches that crashed, costs the enforcement used to skip, a risk ceiling the
planner used to waive, and a daily cap concurrent charges used to overshoot.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.policies import evaluate_wallet_policy

pytestmark = pytest.mark.dormant


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _wallet(client: AsyncClient, agent_id: str) -> str:
    headers = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": f"{agent_id} sponsor",
            "email": f"{agent_id}@example.com",
            "initial_credits": 10000,
            "require_kyc": False,
        },
        headers=headers,
    )
    assert sponsor.status_code == 201
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor.json()["wallet_id"],
            "agent_id": agent_id,
            "budget_credits": 1000,
        },
        headers=headers,
    )
    assert agent.status_code == 201
    return agent.json()["wallet_id"]


ADMIN = {"X-API-Key": "test-key"}


def _planner_payload(wallet_id: str, action_extra: dict, tier: object = "low") -> dict:
    ctx: dict = {
        "candidate_actions": [
            {"id": "mystery", "service": "agent_comms", **action_extra}
        ]
    }
    if tier is not None:
        ctx["tier"] = tier
    return {
        "state": {
            "wallet_id": wallet_id,
            "agent_id": "a1",
            "task_id": "t1",
            "request_id": "break-1",
            "wallet_balance": 100,
            "daily_spend_used": 0,
            "daily_limit": 100,
            "rate_limit_headroom": 1,
            "service_health": {"agent_comms": "healthy"},
            "simulation_flags": {"agent_comms": False},
            "auth_scope": ["invoke"],
            "task_context": ctx,
            "remaining_budget": 10,
            "slo_window_seconds": 1,
        },
        "max_actions": 2,
    }


# --- Malformed patch: explicit null on NOT NULL columns used to 500 ---------
@pytest.mark.anyio
@pytest.mark.parametrize(
    "field",
    [
        "risk_tier",
        "name",
        "require_real_effects",
        "human_approval_required",
        "is_active",
    ],
)
async def test_policy_patch_rejects_explicit_null(client, clean_database, field):
    wallet_id = await _wallet(client, f"patch-null-{field}")
    created = await client.post(
        "/v1/policies",
        json={"wallet_id": wallet_id, "name": "P", "risk_tier": "low"},
        headers=ADMIN,
    )
    assert created.status_code == 201
    policy_id = created.json()["policy_id"]

    resp = await client.patch(
        f"/v1/policies/{policy_id}", json={field: None}, headers=ADMIN
    )
    assert resp.status_code == 422, resp.text

    stored = await client.get(f"/v1/policies/{policy_id}", headers=ADMIN)
    assert stored.status_code == 200
    assert stored.json()["risk_tier"] == "low"
    assert stored.json()["name"] == "P"


@pytest.mark.anyio
async def test_policy_patch_null_still_clears_nullable_caps(client, clean_database):
    """Nullable columns keep their clear-the-restriction meaning."""
    wallet_id = await _wallet(client, "patch-null-caps")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "P",
            "max_cost_per_action": 3,
            "daily_spend_limit": 30,
        },
        headers=ADMIN,
    )
    assert created.status_code == 201
    policy_id = created.json()["policy_id"]

    resp = await client.patch(
        f"/v1/policies/{policy_id}",
        json={"max_cost_per_action": None, "daily_spend_limit": None},
        headers=ADMIN,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_cost_per_action"] is None
    assert resp.json()["daily_spend_limit"] is None


# --- Unknown or negative cost used to waive the money caps -------------------
@pytest.mark.anyio
async def test_policy_denies_unknown_cost_under_caps(client, clean_database):
    wallet_id = await _wallet(client, "cost-unknown")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Caps",
            "max_cost_per_action": 1,
            "daily_spend_limit": 10,
        },
        headers=ADMIN,
    )
    assert created.status_code == 201

    for kwargs in (
        {"estimated_cost": None, "daily_spend_used": 0},
        {"estimated_cost": None, "daily_spend_used": 5},
    ):
        evaluation = await evaluate_wallet_policy(
            wallet_id=wallet_id, tool_name="t", **kwargs
        )
        assert evaluation.allowed is False
        assert evaluation.reason == "cost_unknown"

    # No caps set: an unknown cost has nothing to check against, still allowed.
    wallet_id2 = await _wallet(client, "cost-unknown-nocaps")
    created2 = await client.post(
        "/v1/policies",
        json={"wallet_id": wallet_id2, "name": "No caps"},
        headers=ADMIN,
    )
    assert created2.status_code == 201
    evaluation = await evaluate_wallet_policy(
        wallet_id=wallet_id2, tool_name="t", estimated_cost=None
    )
    assert evaluation.allowed is True


@pytest.mark.anyio
async def test_policy_denies_negative_cost(client, clean_database):
    wallet_id = await _wallet(client, "cost-negative")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Caps",
            "max_cost_per_action": 1,
            "daily_spend_limit": 10,
        },
        headers=ADMIN,
    )
    assert created.status_code == 201

    evaluation = await evaluate_wallet_policy(
        wallet_id=wallet_id,
        tool_name="t",
        estimated_cost=-50.0,
        daily_spend_used=0,
    )
    assert evaluation.allowed is False
    assert evaluation.reason == "invalid_estimated_cost"


@pytest.mark.anyio
async def test_planner_rejects_candidate_without_cost(client, clean_database):
    wallet_id = await _wallet(client, "planner-nocost")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Tiny caps",
            "max_cost_per_action": 1,
            "daily_spend_limit": 1,
        },
        headers=ADMIN,
    )
    assert created.status_code == 201

    resp = await client.post(
        "/v1/planner/optimize",
        json=_planner_payload(wallet_id, {}),
        headers=ADMIN,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_actions"] == []
    assert body["policy_reasons"] == {"mystery": "cost_unknown"}


@pytest.mark.anyio
async def test_planner_rejects_negative_cost_candidate(client, clean_database):
    wallet_id = await _wallet(client, "planner-negcost")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Tiny caps",
            "max_cost_per_action": 1,
            "daily_spend_limit": 100,
        },
        headers=ADMIN,
    )
    assert created.status_code == 201

    resp = await client.post(
        "/v1/planner/optimize",
        json=_planner_payload(wallet_id, {"credit_cost": -50}),
        headers=ADMIN,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_actions"] == []
    assert body["policy_reasons"] == {"mystery": "invalid_estimated_cost"}


# --- Unstated task tier used to waive the risk ceiling ------------------------
@pytest.mark.anyio
async def test_planner_unstated_tier_denied_under_low_bundle(client, clean_database):
    wallet_id = await _wallet(client, "planner-notier")
    created = await client.post(
        "/v1/policies",
        json={"wallet_id": wallet_id, "name": "Low only", "risk_tier": "low"},
        headers=ADMIN,
    )
    assert created.status_code == 201

    resp = await client.post(
        "/v1/planner/optimize",
        json=_planner_payload(wallet_id, {"credit_cost": 0.5}, tier=None),
        headers=ADMIN,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_actions"] == []
    assert body["policy_reasons"] == {"mystery": "risk_tier_not_allowed"}


# --- Concurrent charges used to overshoot the daily cap ----------------------
@pytest.mark.anyio
async def test_concurrent_charges_respect_daily_cap(client, clean_database):
    wallet_id = await _wallet(client, "charge-race")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Tiny daily cap",
            "allowed_service_categories": ["agent_comms"],
            "daily_spend_limit": 5,
        },
        headers=ADMIN,
    )
    assert created.status_code == 201

    async def charge(i: int):
        return await client.post(
            f"/v1/billing/charge?wallet_id={wallet_id}&service=agent_comms&units=1",
            headers={**ADMIN, "X-Request-ID": f"race-{i}"},
        )

    # Each charge costs 1.5, so the cap of 5 admits exactly three.
    results = await asyncio.gather(*[charge(i) for i in range(5)])
    assert sorted(r.status_code for r in results) == [200, 200, 200, 403, 403]

    extra = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=agent_comms&units=1",
        headers={**ADMIN, "X-Request-ID": "race-extra"},
    )
    assert extra.status_code == 403


# --- Semantic pins: deny always wins, empty means fail closed ----------------
@pytest.mark.anyio
async def test_deny_wins_regardless_of_bundle_order(client, clean_database):
    for agent_suffix, first, second in (
        ("deny-first", {"allowed_tools": ["other-tool"]}, None),
        ("allow-first", None, {"allowed_tools": ["other-tool"]}),
    ):
        wallet_id = await _wallet(client, f"deny-order-{agent_suffix}")
        for spec in (first, second):
            payload: dict = {"wallet_id": wallet_id, "name": "B"}
            if spec:
                payload.update(spec)
            created = await client.post("/v1/policies", json=payload, headers=ADMIN)
            assert created.status_code == 201
        evaluation = await evaluate_wallet_policy(
            wallet_id=wallet_id,
            tool_name="my-tool",
            service_category="agent_comms",
        )
        assert evaluation.allowed is False, agent_suffix
        assert evaluation.reason == "tool_not_allowed", agent_suffix


@pytest.mark.anyio
async def test_empty_allowlist_denies_everything(client, clean_database):
    wallet_id = await _wallet(client, "empty-list")
    created = await client.post(
        "/v1/policies",
        json={"wallet_id": wallet_id, "name": "Deny all", "allowed_tools": []},
        headers=ADMIN,
    )
    assert created.status_code == 201

    for tool in ("any-tool", "other-tool"):
        evaluation = await evaluate_wallet_policy(
            wallet_id=wallet_id, tool_name=tool, service_category="agent_comms"
        )
        assert evaluation.allowed is False, tool
        assert evaluation.reason == "tool_not_allowed", tool


@pytest.mark.anyio
async def test_malformed_allowlist_shape_rejected(client, clean_database):
    wallet_id = await _wallet(client, "bad-shape")
    for bad in ("not-a-list", [1, 2], [["nested"]], [{"tool": "x"}]):
        resp = await client.post(
            "/v1/policies",
            json={"wallet_id": wallet_id, "name": "Bad", "allowed_tools": bad},
            headers=ADMIN,
        )
        assert resp.status_code == 422, (bad, resp.text)
