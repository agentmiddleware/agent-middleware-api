import app.optimizer.planner as planner
from app.schemas.optimizer import OptimizerRequest, OptimizerState


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
