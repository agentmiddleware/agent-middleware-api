from __future__ import annotations

from fastapi import APIRouter

from app.optimizer.candidates import get_candidate_actions
from app.optimizer.planner import optimize_action_set
from app.schemas.optimizer import OptimizerRequest, OptimizerResponse

router = APIRouter(prefix="/v1/planner", tags=["optimizer"])


@router.post("/optimize", response_model=OptimizerResponse)
async def optimize_endpoint(req: OptimizerRequest) -> OptimizerResponse:
    candidates = get_candidate_actions(req.state)
    plan = optimize_action_set(req.state, candidates, req)
    return OptimizerResponse(**plan)
