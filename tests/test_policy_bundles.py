from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.audit_log import list_audit_events
from app.services.service_registry import get_service_registry


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _wallet(client: AsyncClient, agent_id: str = "policy-agent") -> str:
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


@pytest.mark.anyio
async def test_policy_crud_requires_bootstrap_admin(client, clean_database):
    wallet_id = await _wallet(client, "policy-crud")
    created = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Strict agent policy",
            "allowed_tools": ["policy-echo"],
            "allowed_service_categories": ["agent_comms"],
            "max_cost_per_action": 3,
        },
        headers={"X-API-Key": "test-key"},
    )
    assert created.status_code == 201
    policy = created.json()
    assert policy["policy_id"].startswith("polb-")

    listed = await client.get(
        f"/v1/policies?wallet_id={wallet_id}",
        headers={"X-API-Key": "test-key"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patched = await client.patch(
        f"/v1/policies/{policy['policy_id']}",
        json={"max_cost_per_action": 1, "is_active": False},
        headers={"X-API-Key": "test-key"},
    )
    assert patched.status_code == 200
    assert patched.json()["max_cost_per_action"] == 1.0
    assert patched.json()["is_active"] is False

    key = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "runtime"},
        headers={"X-API-Key": "test-key"},
    )
    assert key.status_code == 201
    denied = await client.get(
        f"/v1/policies?wallet_id={wallet_id}",
        headers={"X-API-Key": key.json()["api_key"]},
    )
    assert denied.status_code == 403


@pytest.mark.anyio
async def test_mcp_policy_denies_disallowed_tool_before_charge(client, clean_database):
    registry = get_service_registry()

    def blocked_tool() -> dict:
        return {"ran": True}

    registry.register_local(
        service_id="policy-blocked-tool",
        name="Policy Blocked Tool",
        description="Should be blocked by policy",
        category=ServiceCategory.AGENT_COMMS,
        func=blocked_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        wallet_id = await _wallet(client, "policy-mcp")
        policy = await client.post(
            "/v1/policies",
            json={
                "wallet_id": wallet_id,
                "name": "Only another tool",
                "allowed_tools": ["some-other-tool"],
            },
            headers={"X-API-Key": "test-key"},
        )
        assert policy.status_code == 201

        response = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "policy-deny-1",
                "method": "tools/call",
                "params": {
                    "name": "policy-blocked-tool",
                    "arguments": {},
                    "mcpContext": {"wallet_id": wallet_id},
                },
            },
            headers={"X-API-Key": "test-key"},
        )
        assert response.status_code == 200
        assert response.json()["error"]["message"] == "tool_not_allowed"

        ledger = await client.get(
            f"/v1/billing/ledger/{wallet_id}",
            headers={"X-API-Key": "test-key"},
        )
        assert ledger.status_code == 200
        assert all(
            "policy-blocked-tool" not in entry.get("description", "")
            for entry in ledger.json()["entries"]
        )

        events = await list_audit_events(wallet_id=wallet_id, tool="policy-blocked-tool")
        assert len(events) == 1
        assert events[0].ok is False
        assert events[0].error == "tool_not_allowed"
        assert events[0].metadata["policy_id"] == policy.json()["policy_id"]
    finally:
        registry.unregister_local("policy-blocked-tool")


@pytest.mark.anyio
async def test_billing_policy_denies_disallowed_category(client, clean_database):
    wallet_id = await _wallet(client, "policy-billing")
    policy = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "No IoT",
            "allowed_service_categories": ["agent_comms"],
        },
        headers={"X-API-Key": "test-key"},
    )
    assert policy.status_code == 201

    response = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=iot_bridge&units=1",
        headers={"X-API-Key": "test-key", "X-Request-ID": "policy-billing-deny"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "service_category_not_allowed"

    events = await list_audit_events(
        wallet_id=wallet_id,
        request_id="policy-billing-deny",
    )
    assert len(events) == 1
    assert events[0].error == "service_category_not_allowed"
    assert events[0].metadata["policy_id"] == policy.json()["policy_id"]


@pytest.mark.anyio
async def test_billing_policy_denies_over_cost_charge(client, clean_database):
    wallet_id = await _wallet(client, "policy-billing-cost")
    policy = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Cheap actions only",
            "allowed_service_categories": ["agent_comms"],
            "max_cost_per_action": 1,
        },
        headers={"X-API-Key": "test-key"},
    )
    assert policy.status_code == 201

    response = await client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=agent_comms&units=2",
        headers={"X-API-Key": "test-key", "X-Request-ID": "policy-cost-deny"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "max_cost_per_action_exceeded"


@pytest.mark.anyio
async def test_planner_policy_rejects_actions(client, clean_database):
    wallet_id = await _wallet(client, "policy-planner")
    policy = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Only agent comms",
            "allowed_service_categories": ["agent_comms"],
        },
        headers={"X-API-Key": "test-key"},
    )
    assert policy.status_code == 201

    response = await client.post(
        "/v1/planner/optimize",
        json={
            "state": {
                "wallet_id": wallet_id,
                "agent_id": "a1",
                "task_id": "t1",
                "request_id": "policy-planner-1",
                "wallet_balance": 100,
                "daily_spend_used": 0,
                "daily_limit": 100,
                "rate_limit_headroom": 1,
                "service_health": {"iot_bridge": "healthy", "agent_comms": "healthy"},
                "simulation_flags": {"iot_bridge": False, "agent_comms": False},
                "auth_scope": ["invoke"],
                "task_context": {
                    "tier": "high",
                    "candidate_actions": [
                        {
                            "id": "bad-iot",
                            "service": "iot_bridge",
                            "credit_cost": 1,
                            "latency_ms": 10,
                            "risk_score": 0.01,
                            "expected_value": 10,
                            "reliability": 1,
                        },
                        {
                            "id": "good-comms",
                            "service": "agent_comms",
                            "credit_cost": 1,
                            "latency_ms": 10,
                            "risk_score": 0.01,
                            "expected_value": 5,
                            "reliability": 1,
                        },
                    ],
                },
                "remaining_budget": 10,
                "slo_window_seconds": 1,
            },
            "max_actions": 2,
        },
        headers={"X-API-Key": "test-key", "X-Request-ID": "policy-planner-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["policy_reasons"]["bad-iot"] == "service_category_not_allowed"
    assert body["rejected_actions"][0]["policy_id"] == policy.json()["policy_id"]
    assert body["governance"]["policy_ids"] == [policy.json()["policy_id"]]
