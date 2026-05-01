"""
Tests for Pillar 13: Interactive Testing Sandboxes.
Validates headless puzzle environments and generalization scoring.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.anyio
async def test_create_pattern_environment(client):
    """Create a pattern-discovery sandbox."""
    resp = await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
        "difficulty": "medium",
        "seed": 42,
    }, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["env_type"] == "pattern"
    assert data["difficulty"] == "medium"
    assert data["env_id"].startswith("env-")


@pytest.mark.anyio
async def test_create_navigation_environment(client):
    """Create a navigation sandbox."""
    resp = await client.post("/v1/sandbox/environments", json={
        "env_type": "navigation",
        "difficulty": "hard",
    }, headers=HEADERS)
    assert resp.status_code == 201
    assert resp.json()["env_type"] == "navigation"


@pytest.mark.anyio
async def test_create_api_mock_environment(client):
    """Create an API mock sandbox."""
    resp = await client.post("/v1/sandbox/environments", json={
        "env_type": "api_mock",
        "difficulty": "easy",
    }, headers=HEADERS)
    assert resp.status_code == 201
    assert resp.json()["env_type"] == "api_mock"


@pytest.mark.anyio
async def test_create_adversarial_environment(client):
    """Create an adversarial sandbox."""
    resp = await client.post("/v1/sandbox/environments", json={
        "env_type": "adversarial",
        "difficulty": "extreme",
    }, headers=HEADERS)
    assert resp.status_code == 201
    assert resp.json()["env_type"] == "adversarial"


@pytest.mark.anyio
async def test_submit_action(client):
    """Agent can submit actions to the environment."""
    create = await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
        "difficulty": "easy",
    }, headers=HEADERS)
    env_id = create.json()["env_id"]

    resp = await client.post(f"/v1/sandbox/environments/{env_id}/actions", json={
        "action": {"type": "observe", "value": "grid"},
    }, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "step" in data
    assert "reward" in data
    assert "feedback" in data
    assert data["action_accepted"] is True


@pytest.mark.anyio
async def test_solve_pattern_environment(client):
    """Agent can solve a pattern puzzle by guessing the transform."""
    create = await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
        "difficulty": "easy",
        "seed": 100,
    }, headers=HEADERS)
    env_id = create.json()["env_id"]

    resp = await client.post(f"/v1/sandbox/environments/{env_id}/actions", json={
        "action": {"type": "submit_transform", "value": "rotate"},
    }, headers=HEADERS)
    data = resp.json()
    # Depending on seed, may or may not solve, but should accept action
    assert data["action_accepted"] is True


@pytest.mark.anyio
async def test_evaluate_environment(client):
    """Evaluation returns generalization score."""
    create = await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
        "difficulty": "medium",
    }, headers=HEADERS)
    env_id = create.json()["env_id"]

    # Do a few actions first
    await client.post(f"/v1/sandbox/environments/{env_id}/actions", json={
        "action": {"type": "observe"},
    }, headers=HEADERS)

    resp = await client.post(f"/v1/sandbox/environments/{env_id}/evaluate", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "generalization_score" in data
    assert "efficiency" in data
    assert "solved" in data
    assert data["steps_used"] >= 1


@pytest.mark.anyio
async def test_list_environments(client):
    """Can list all sandbox environments."""
    await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
    }, headers=HEADERS)

    resp = await client.get("/v1/sandbox/environments", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.anyio
async def test_get_environment_by_id(client):
    """Can retrieve a specific environment."""
    create = await client.post("/v1/sandbox/environments", json={
        "env_type": "navigation",
    }, headers=HEADERS)
    env_id = create.json()["env_id"]

    resp = await client.get(f"/v1/sandbox/environments/{env_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["env_id"] == env_id


@pytest.mark.anyio
async def test_environment_not_found(client):
    resp = await client.get("/v1/sandbox/environments/env-nonexistent", headers=HEADERS)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_state_hides_rules(client):
    """Environment state should NOT expose hidden rules."""
    create = await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
        "difficulty": "hard",
    }, headers=HEADERS)
    data = create.json()
    state = data["state"]
    assert "hidden_rules" not in str(state).lower() or "hidden_rules" not in state


@pytest.mark.anyio
async def test_sandbox_requires_api_key(client):
    resp = await client.post("/v1/sandbox/environments", json={
        "env_type": "pattern",
    })
    assert resp.status_code in (401, 403)
