"""
Tests for replay protection: the durable claim-once primitive and the
ReplayProtectionMiddleware that rejects replayed mutating requests.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.durable_state import get_durable_state
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _planner_body():
    return {
        "state": {
            "wallet_id": "w1",
            "agent_id": "a1",
            "task_id": "t1",
            "request_id": "r1",
            "wallet_balance": 100,
            "daily_spend_used": 0,
            "daily_limit": 100,
            "rate_limit_headroom": 1,
            "service_health": {},
            "simulation_flags": {},
            "auth_scope": ["invoke"],
            "task_context": {"candidate_actions": []},
            "remaining_budget": 10,
            "slo_window_seconds": 2,
        }
    }


# --- claim_once primitive ---


@pytest.mark.anyio
async def test_claim_once_first_claim_succeeds_then_replays_fail():
    store = get_durable_state()
    key = f"test-nonce-{uuid.uuid4()}"

    assert await store.claim_once(key, 60) is True
    assert await store.claim_once(key, 60) is False
    assert await store.claim_once(key, 60) is False


@pytest.mark.anyio
async def test_claim_once_distinct_keys_are_independent():
    store = get_durable_state()
    a = f"test-nonce-{uuid.uuid4()}"
    b = f"test-nonce-{uuid.uuid4()}"

    assert await store.claim_once(a, 60) is True
    assert await store.claim_once(b, 60) is True


@pytest.mark.anyio
async def test_claim_once_reclaimable_after_expiry():
    store = get_durable_state()
    key = f"test-nonce-{uuid.uuid4()}"

    assert await store.claim_once(key, 60) is True
    # Force the in-memory claim to look expired, then it must be reclaimable.
    if key in store._nonce_mem:
        store._nonce_mem[key] = 0.0
    assert await store.claim_once(key, 60) is True


# --- middleware behavior ---


@pytest.mark.anyio
async def test_replayed_request_is_rejected(client):
    idem = str(uuid.uuid4())
    headers = {"Idempotency-Key": idem}

    first = await client.post(
        "/v1/planner/optimize", json=_planner_body(), headers=headers
    )
    assert first.status_code != 409

    second = await client.post(
        "/v1/planner/optimize", json=_planner_body(), headers=headers
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "request_replayed"
    assert second.headers.get("Idempotency-Replayed") == "true"


@pytest.mark.anyio
async def test_distinct_idempotency_keys_both_pass(client):
    body = _planner_body()
    r1 = await client.post(
        "/v1/planner/optimize",
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    r2 = await client.post(
        "/v1/planner/optimize",
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r1.status_code != 409
    assert r2.status_code != 409


@pytest.mark.anyio
async def test_no_idempotency_key_is_not_enforced(client):
    """Backwards compatible: absent the header, repeats are allowed."""
    body = _planner_body()
    r1 = await client.post("/v1/planner/optimize", json=body)
    r2 = await client.post("/v1/planner/optimize", json=body)
    assert r1.status_code != 409
    assert r2.status_code != 409
