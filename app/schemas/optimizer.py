from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class OptimizerState(BaseModel):
    wallet_id: str
    agent_id: str
    task_id: str
    request_id: str
    wallet_balance: float = Field(..., ge=0)
    daily_spend_used: float = Field(..., ge=0)
    daily_limit: float = Field(..., ge=0)
    rate_limit_headroom: float = Field(..., ge=0, le=1)
    service_health: Dict[str, Literal["healthy", "degraded", "down"]]
    simulation_flags: Dict[str, bool]
    auth_scope: List[str]
    task_context: Dict
    remaining_budget: float = Field(..., ge=0)
    slo_window_seconds: int = Field(30, ge=1)


class OptimizerRequest(BaseModel):
    state: OptimizerState
    objective_overrides: Optional[Dict[str, float]] = None
    max_actions: Optional[int] = Field(default=5, ge=1)
    require_real_effects: bool = False


class OptimizerResponse(BaseModel):
    status: Literal["Optimal", "HeuristicFallback", "Infeasible"]
    selected_actions: List[Dict]
    rejected_actions: List[Dict]
    policy_reasons: Dict[str, str]
    expected_utility: float
    totals: Dict[str, float]
    constraint_margins: Dict[str, float]
