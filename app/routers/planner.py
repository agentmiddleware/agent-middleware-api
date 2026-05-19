from __future__ import annotations

from fastapi import APIRouter, Request

from app.optimizer.candidates import get_candidate_actions
from app.optimizer.planner import optimize_action_set
from app.core.auth import AuthContext
from app.core.config import get_settings
from app.policy.decisions import evaluate_governed_action
from app.schemas.optimizer import OptimizerRequest, OptimizerResponse
from app.services.audit_log import record_audit_event

router = APIRouter(prefix="/v1/planner", tags=["optimizer"])


def _planner_auth_context(request: Request) -> AuthContext | None:
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return None
    valid_keys = [
        key.strip()
        for key in get_settings().VALID_API_KEYS.split(",")
        if key.strip()
    ]
    if api_key.strip() in valid_keys:
        return AuthContext(source="env", raw_key=api_key.strip(), is_bootstrap_admin=True)
    return AuthContext(source="unknown", raw_key=api_key.strip())


@router.post("/optimize", response_model=OptimizerResponse)
async def optimize_endpoint(req: OptimizerRequest, request: Request) -> OptimizerResponse:
    candidates = get_candidate_actions(req.state)
    plan = optimize_action_set(req.state, candidates, req)
    request_id = request.headers.get("X-Request-ID") or req.state.request_id
    decision = evaluate_governed_action(
        auth=_planner_auth_context(request),
        wallet_id=req.state.wallet_id,
        action_type="planner.optimize",
        target="planner",
        estimated_cost=plan["totals"].get("cost"),
        request_id=request_id,
        allowed=plan["status"] != "Infeasible",
        reason="allowed" if plan["status"] != "Infeasible" else "infeasible",
    )
    audit_event = await record_audit_event(
        event="planner.optimize",
        wallet_id=req.state.wallet_id,
        tool="planner",
        endpoint="/v1/planner/optimize",
        auth_source=decision.auth_source,
        key_id=decision.key_id,
        policy_decision_id=decision.decision_id,
        request_id=request_id,
        ok=True,
        metadata={
            "status": plan["status"],
            "selected_count": len(plan["selected_actions"]),
            "rejected_count": len(plan["rejected_actions"]),
            "policy_reason": decision.reason,
            "simulation_flags": req.state.simulation_flags,
            "constraint_margins": plan["constraint_margins"],
        },
    )
    plan["governance"] = {
        "request_id": request_id,
        "wallet_id": req.state.wallet_id,
        "policy_decision_id": decision.decision_id,
        "audit_event_id": audit_event.event_id,
    }
    return OptimizerResponse(**plan)
