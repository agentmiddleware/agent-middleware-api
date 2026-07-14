"""Cross-tenant isolation regression tests for routers that previously
trusted a client-supplied wallet/tenant id without an ownership check.

Covers three confirmed IDOR / missing-auth findings:
  - telemetry_scope: pipelines are wallet-scoped and must not be readable,
    mutable, or enumerable across tenants.
  - planner/optimize: must authenticate and enforce wallet ownership before
    reading policy bundles or writing signed audit events.
  - sandbox/behavioral get/destroy/execute: must require auth + env ownership.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_trust_helpers import provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _optimizer_body(wallet_id: str) -> dict:
    return {
        "state": {
            "wallet_id": wallet_id,
            "agent_id": "a1",
            "task_id": "t1",
            "request_id": "r1",
            "wallet_balance": 100,
            "daily_spend_used": 0,
            "daily_limit": 100,
            "rate_limit_headroom": 1.0,
            "service_health": {"svc1": "healthy"},
            "simulation_flags": {"svc1": False},
            "auth_scope": ["invoke"],
            "task_context": {"tier": "medium"},
            "remaining_budget": 20,
            "slo_window_seconds": 2,
        }
    }


# --------------------------------------------------------------------------
# telemetry-scope
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_telemetry_pipeline_not_readable_across_tenants(client, clean_database):
    a = await provision_agent_wallet(client)
    b = await provision_agent_wallet(client)

    create = await client.post(
        "/v1/telemetry-scope/pipelines",
        json={
            "tenant_id": a["agent_wallet_id"],
            "service_name": "svc",
            "git_repo_url": "https://github.com/a/secret",
            "webhook_url": "https://a.example/hook",
        },
        headers=a["agent_headers"],
    )
    assert create.status_code == 201
    pipeline_id = create.json()["pipeline_id"]

    # Wallet B may not read, ingest into, or trigger auto-PR on A's pipeline.
    assert (
        await client.get(
            f"/v1/telemetry-scope/pipelines/{pipeline_id}", headers=b["agent_headers"]
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/v1/telemetry-scope/pipelines/{pipeline_id}/stats",
            headers=b["agent_headers"],
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/v1/telemetry-scope/pipelines/{pipeline_id}/events",
            json={"events": [{"latency_ms": 1}]},
            headers=b["agent_headers"],
        )
    ).status_code == 403

    # Owner still has access.
    assert (
        await client.get(
            f"/v1/telemetry-scope/pipelines/{pipeline_id}", headers=a["agent_headers"]
        )
    ).status_code == 200


@pytest.mark.anyio
async def test_telemetry_list_pipelines_scoped_to_caller(client, clean_database):
    a = await provision_agent_wallet(client)
    b = await provision_agent_wallet(client)
    await client.post(
        "/v1/telemetry-scope/pipelines",
        json={"tenant_id": a["agent_wallet_id"], "service_name": "svc-a"},
        headers=a["agent_headers"],
    )

    # B lists (even trying to spoof A's tenant_id via query) and sees nothing of A's.
    resp = await client.get(
        f"/v1/telemetry-scope/pipelines?tenant_id={a['agent_wallet_id']}",
        headers=b["agent_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.anyio
async def test_telemetry_create_pipeline_for_other_wallet_denied(client, clean_database):
    a = await provision_agent_wallet(client)
    b = await provision_agent_wallet(client)
    resp = await client.post(
        "/v1/telemetry-scope/pipelines",
        json={"tenant_id": a["agent_wallet_id"], "service_name": "svc"},
        headers=b["agent_headers"],
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# planner/optimize
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_planner_optimize_requires_auth(client, clean_database):
    resp = await client.post("/v1/planner/optimize", json=_optimizer_body("w-victim"))
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_planner_optimize_rejects_cross_wallet(client, clean_database):
    a = await provision_agent_wallet(client)
    b = await provision_agent_wallet(client)
    # B authenticates but names A's wallet in the request state.
    resp = await client.post(
        "/v1/planner/optimize",
        json=_optimizer_body(a["agent_wallet_id"]),
        headers=b["agent_headers"],
    )
    assert resp.status_code == 403

    # B optimizing for its own wallet works.
    ok = await client.post(
        "/v1/planner/optimize",
        json=_optimizer_body(b["agent_wallet_id"]),
        headers=b["agent_headers"],
    )
    assert ok.status_code == 200


# --------------------------------------------------------------------------
# sandbox/behavioral
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_sandbox_env_not_accessible_across_tenants(client, clean_database):
    a = await provision_agent_wallet(client)
    b = await provision_agent_wallet(client)

    create = await client.post(
        "/v1/sandbox/behavioral/environments",
        json={
            "name": "a-env",
            "environment_type": "mcp_sandbox",
            "wallet_id": a["agent_wallet_id"],
        },
        headers=a["agent_headers"],
    )
    assert create.status_code == 201
    env_id = create.json()["env_id"]

    # Unauthenticated read is rejected outright.
    assert (
        await client.get(f"/v1/sandbox/behavioral/environments/{env_id}")
    ).status_code == 401

    # Wallet B cannot read or destroy A's environment.
    assert (
        await client.get(
            f"/v1/sandbox/behavioral/environments/{env_id}", headers=b["agent_headers"]
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/v1/sandbox/behavioral/environments/{env_id}", headers=b["agent_headers"]
        )
    ).status_code == 403

    # Owner can read.
    assert (
        await client.get(
            f"/v1/sandbox/behavioral/environments/{env_id}", headers=a["agent_headers"]
        )
    ).status_code == 200


@pytest.mark.anyio
async def test_bootstrap_admin_key_matches_via_constant_time_compare(clean_database):
    """A configured bootstrap key is accepted as admin; a key that merely
    shares a prefix must not match.

    Locks in the constant-time comparison against VALID_API_KEYS -- the match
    result must be identical to the previous membership test."""
    from fastapi import HTTPException

    from app.core.auth import get_auth_context

    admin = await get_auth_context("test-key")
    assert admin.is_bootstrap_admin is True
    assert admin.source == "env"

    # A key that shares a prefix with the valid key must NOT match; it falls
    # through to the DB registry and, absent a record, is rejected.
    with pytest.raises(HTTPException) as excinfo:
        await get_auth_context("test-key-but-longer")
    assert excinfo.value.status_code == 403
