from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Python's JSON parser accepts NaN/Infinity tokens and ``ge`` alone lets
# Infinity through; either would poison expected_utility and the margins.
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class OptimizerState(BaseModel):
    wallet_id: str
    agent_id: str
    task_id: str
    request_id: str
    wallet_balance: float = Field(..., ge=0, allow_inf_nan=False)
    daily_spend_used: float = Field(..., ge=0, allow_inf_nan=False)
    daily_limit: float = Field(..., ge=0, allow_inf_nan=False)
    rate_limit_headroom: float = Field(..., ge=0, le=1, allow_inf_nan=False)
    service_health: Dict[str, Literal["healthy", "degraded", "down"]]
    simulation_flags: Dict[str, bool]
    auth_scope: List[str]
    task_context: Dict
    remaining_budget: float = Field(..., ge=0, allow_inf_nan=False)
    slo_window_seconds: int = Field(30, ge=1)


class OptimizerRequest(BaseModel):
    state: OptimizerState
    objective_overrides: Optional[Dict[str, FiniteFloat]] = None
    max_actions: Optional[int] = Field(default=5, ge=1)
    require_real_effects: bool = False


class OptimizerResponse(BaseModel):
    # "Optimal" was only reachable through a MILP branch that never ran (its
    # solver was never a declared dependency). Selection is the deterministic
    # greedy heuristic, so these are the two statuses the planner can emit.
    status: Literal["HeuristicFallback", "Infeasible"]
    selected_actions: List[Dict]
    rejected_actions: List[Dict]
    policy_reasons: Dict[str, str]
    expected_utility: float
    totals: Dict[str, float]
    constraint_margins: Dict[str, float]
    governance: Optional[Dict] = None
