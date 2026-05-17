from __future__ import annotations

from typing import Any

from app.optimizer.policy import get_risk_budget, is_admissible
from app.schemas.optimizer import OptimizerRequest, OptimizerState

try:
    import pulp
except Exception:  # pragma: no cover
    pulp = None


def _score(action: dict[str, Any], lambdas: dict[str, float]) -> float:
    return (
        action.get("expected_value", 0.0) * action.get("reliability", 1.0)
        - lambdas["cost"] * action.get("credit_cost", 0.0)
        - lambdas["latency"] * action.get("latency_ms", 0.0) / 1000.0
        - lambdas["risk"] * action.get("risk_score", 0.0)
    )


def _pack_response(status: str, selected: list[dict], rejected: list[dict], state: OptimizerState, risk_budget: float, lambdas: dict[str, float]) -> dict:
    total_cost = sum(a.get("credit_cost", 0.0) for a in selected)
    total_latency = sum(a.get("latency_ms", 0.0) for a in selected)
    total_risk = sum(a.get("risk_score", 0.0) for a in selected)
    expected_utility = sum(_score(a, lambdas) for a in selected)
    return {
        "status": status,
        "selected_actions": selected,
        "rejected_actions": rejected,
        "expected_utility": expected_utility,
        "totals": {
            "cost": total_cost,
            "latency_ms": total_latency,
            "risk": total_risk,
        },
        "constraint_margins": {
            "budget_left": state.remaining_budget - total_cost,
            "latency_left": state.slo_window_seconds * 1000 - total_latency,
            "risk_left": risk_budget - total_risk,
        },
    }


def _greedy_heuristic(candidates: list[dict], state: OptimizerState, risk_budget: float, max_actions: int, lambdas: dict[str, float]) -> list[dict]:
    scored = sorted(candidates, key=lambda a: _score(a, lambdas), reverse=True)
    selected: list[dict] = []
    total_cost = 0.0
    total_latency = 0.0
    total_risk = 0.0
    for action in scored:
        c = action.get("credit_cost", 0.0)
        l = action.get("latency_ms", 0.0)
        r = action.get("risk_score", 0.0)
        if total_cost + c > state.remaining_budget:
            continue
        if total_latency + l > state.slo_window_seconds * 1000:
            continue
        if total_risk + r > risk_budget:
            continue
        selected.append(action)
        total_cost += c
        total_latency += l
        total_risk += r
        if len(selected) >= max_actions:
            break
    return selected


def optimize_action_set(state: OptimizerState, candidates: list[dict], req: OptimizerRequest) -> dict:
    lambdas = {"cost": 0.8, "latency": 0.3, "risk": 2.0}
    if req.objective_overrides:
        for k in lambdas:
            if k in req.objective_overrides:
                lambdas[k] = float(req.objective_overrides[k])

    risk_budget = get_risk_budget(state.task_context.get("tier", "medium"))
    admissible: list[dict] = []
    rejected: list[dict] = []

    for action in candidates:
        ok, reason = is_admissible(action, state, req.require_real_effects)
        if ok:
            admissible.append(action)
        else:
            rejected.append({"id": action.get("id"), "reason": reason})

    if not admissible:
        return _pack_response("Infeasible", [], rejected, state, risk_budget, lambdas)

    max_actions = 5 if req.max_actions is None else req.max_actions

    if pulp is not None:
        try:
            prob = pulp.LpProblem("AgentPlanner", pulp.LpMaximize)
            x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(len(admissible))}
            prob += pulp.lpSum(x[i] * _score(action, lambdas) for i, action in enumerate(admissible))
            prob += pulp.lpSum(x[i] * action.get("credit_cost", 0.0) for i, action in enumerate(admissible)) <= state.remaining_budget
            prob += pulp.lpSum(x[i] * action.get("latency_ms", 0.0) for i, action in enumerate(admissible)) <= state.slo_window_seconds * 1000
            prob += pulp.lpSum(x[i] * action.get("risk_score", 0.0) for i, action in enumerate(admissible)) <= risk_budget
            prob += pulp.lpSum(x[i] for i in range(len(admissible))) <= max_actions
            status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
            if pulp.LpStatus[status] == "Optimal":
                selected = [admissible[i] for i in range(len(admissible)) if x[i].value() and x[i].value() > 0.5]
                if selected:
                    return _pack_response("Optimal", selected, rejected, state, risk_budget, lambdas)
                return _pack_response("Infeasible", [], rejected, state, risk_budget, lambdas)
        except Exception:
            pass

    selected = _greedy_heuristic(admissible, state, risk_budget, max_actions, lambdas)
    status = "HeuristicFallback" if selected else "Infeasible"
    return _pack_response(status, selected, rejected, state, risk_budget, lambdas)
