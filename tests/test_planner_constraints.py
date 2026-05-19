import app.optimizer.planner as planner
from app.schemas.optimizer import OptimizerRequest, OptimizerState
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.audit_log import list_audit_events


def _state(tier="low", service_health=None):
    return OptimizerState(
        wallet_id="w1",
        agent_id="a1",
        task_id="t1",
        request_id="r1",
        wallet_balance=100,
        daily_spend_used=0,
        daily_limit=100,
        rate_limit_headroom=1.0,
        service_health=service_health or {"svc1": "healthy"},
        simulation_flags={"svc1": False},
        auth_scope=["invoke"],
        task_context={"tier": tier},
        remaining_budget=3,
        slo_window_seconds=1,
    )


def test_infeasible_when_service_unhealthy():
    state = _state(service_health={"svc1": "down"})
    req = OptimizerRequest(state=state)
    candidates = [{"id": "x", "service": "svc1", "credit_cost": 1, "latency_ms": 10, "risk_score": 0.01, "expected_value": 1, "reliability": 1.0}]
    out = planner.optimize_action_set(state, candidates, req)
    assert out["status"] == "Infeasible"
    assert out["rejected_actions"] == [{"id": "x", "reason": "service_unhealthy"}]
    assert out["policy_reasons"] == {"x": "service_unhealthy"}


def test_fallback_path_when_solver_unavailable(monkeypatch):
    monkeypatch.setattr(planner, "pulp", None)
    state = _state(tier="high")
    req = OptimizerRequest(state=state, max_actions=2)
    candidates = [
        {"id": "x1", "service": "svc1", "credit_cost": 1, "latency_ms": 10, "risk_score": 0.01, "expected_value": 4, "reliability": 1.0},
        {"id": "x2", "service": "svc1", "credit_cost": 2, "latency_ms": 10, "risk_score": 0.01, "expected_value": 3, "reliability": 1.0},
    ]
    out = planner.optimize_action_set(state, candidates, req)
    assert out["status"] == "HeuristicFallback"
    assert len(out["selected_actions"]) <= 2


def test_risk_budget_enforced_by_tier():
    state = _state(tier="low")
    req = OptimizerRequest(state=state)
    candidates = [
        {"id": "safe", "service": "svc1", "credit_cost": 1, "latency_ms": 10, "risk_score": 0.02, "expected_value": 1, "reliability": 1.0},
        {"id": "risky", "service": "svc1", "credit_cost": 1, "latency_ms": 10, "risk_score": 0.2, "expected_value": 10, "reliability": 1.0},
    ]
    out = planner.optimize_action_set(state, candidates, req)
    ids = {x["id"] for x in out["selected_actions"]}
    assert "risky" not in ids
    rejected = {x["id"]: x["reason"] for x in out["rejected_actions"]}
    assert rejected["risky"] == "risk_budget_exceeded"
    assert out["policy_reasons"]["risky"] == "risk_budget_exceeded"


def test_feasible_unselected_candidate_is_not_policy_rejected():
    state = _state(tier="high")
    state.remaining_budget = 10
    req = OptimizerRequest(state=state, max_actions=1)
    candidates = [
        {"id": "winner", "service": "svc1", "credit_cost": 6, "latency_ms": 10, "risk_score": 0.01, "expected_value": 2, "reliability": 1.0},
        {"id": "alternate", "service": "svc1", "credit_cost": 6, "latency_ms": 10, "risk_score": 0.01, "expected_value": 1, "reliability": 1.0},
    ]

    out = planner.optimize_action_set(state, candidates, req)

    assert [action["id"] for action in out["selected_actions"]] == ["winner"]
    assert "alternate" not in {action["id"] for action in out["rejected_actions"]}
    assert "alternate" not in out["policy_reasons"]


def test_individual_budget_violation_maps_to_policy_reason():
    state = _state(tier="high")
    req = OptimizerRequest(state=state)
    candidates = [
        {"id": "too_expensive", "service": "svc1", "credit_cost": 4, "latency_ms": 10, "risk_score": 0.01, "expected_value": 10, "reliability": 1.0},
    ]

    out = planner.optimize_action_set(state, candidates, req)

    assert out["status"] == "Infeasible"
    assert out["rejected_actions"] == [{"id": "too_expensive", "reason": "budget_exceeded"}]
    assert out["policy_reasons"] == {"too_expensive": "budget_exceeded"}


def test_individual_latency_violation_maps_to_policy_reason():
    state = _state(tier="high")
    req = OptimizerRequest(state=state)
    candidates = [
        {"id": "too_slow", "service": "svc1", "credit_cost": 1, "latency_ms": 1001, "risk_score": 0.01, "expected_value": 10, "reliability": 1.0},
    ]

    out = planner.optimize_action_set(state, candidates, req)

    assert out["status"] == "Infeasible"
    assert out["rejected_actions"] == [{"id": "too_slow", "reason": "latency_budget_exceeded"}]
    assert out["policy_reasons"] == {"too_slow": "latency_budget_exceeded"}


def test_solver_empty_solution_returns_infeasible_regression():
    state = _state(tier="high")
    req = OptimizerRequest(state=state)
    candidates = [
        {"id": "x1", "service": "svc1", "credit_cost": 10, "latency_ms": 10, "risk_score": 0.01, "expected_value": 4, "reliability": 1.0},
    ]
    out = planner.optimize_action_set(state, candidates, req)
    assert out["selected_actions"] == []
    assert out["status"] == "Infeasible"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_planner_endpoint_returns_governance_context_and_records_audit(
    client,
    clean_database,
):
    request_id = "req-planner-governance"
    payload = {
        "state": _state(tier="high").model_dump(),
        "max_actions": 1,
    }
    payload["state"]["request_id"] = request_id
    payload["state"]["wallet_id"] = "wallet-planner-governance"
    payload["state"]["task_context"]["candidate_actions"] = [
        {
            "id": "winner",
            "service": "svc1",
            "credit_cost": 1,
            "latency_ms": 10,
            "risk_score": 0.01,
            "expected_value": 4,
            "reliability": 1.0,
        },
        {
            "id": "too_slow",
            "service": "svc1",
            "credit_cost": 1,
            "latency_ms": 2000,
            "risk_score": 0.01,
            "expected_value": 10,
            "reliability": 1.0,
        },
    ]

    response = await client.post(
        "/v1/planner/optimize",
        json=payload,
        headers={"X-API-Key": "test-key", "X-Request-ID": request_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["governance"]["request_id"] == request_id
    assert data["governance"]["wallet_id"] == "wallet-planner-governance"
    assert data["governance"]["audit_event_id"].startswith("audit-")
    assert data["governance"]["policy_decision_id"].startswith("pol-")
    assert data["policy_reasons"] == {"too_slow": "latency_budget_exceeded"}

    events = await list_audit_events(request_id=request_id)
    assert len(events) == 1
    event = events[0]
    assert event.event == "planner.optimize"
    assert event.wallet_id == "wallet-planner-governance"
    assert event.tool == "planner"
    assert event.endpoint == "/v1/planner/optimize"
    assert event.ok is True
    assert event.policy_decision_id == data["governance"]["policy_decision_id"]
    assert event.metadata["status"] == data["status"]
    assert event.metadata["selected_count"] == 1
    assert event.metadata["rejected_count"] == 1
