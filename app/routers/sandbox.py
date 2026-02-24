"""
Interactive Testing Sandboxes Router (Pillar 13)
---------------------------------------------------
Headless puzzle environments for testing agent-built tools'
ability to generalize and adapt without human instruction.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime

from ..core.auth import verify_api_key
from ..core.dependencies import get_sandbox_engine
from ..services.sandbox import SandboxEngine

router = APIRouter(
    prefix="/v1/sandbox",
    tags=["Interactive Testing Sandboxes"],
    dependencies=[Depends(verify_api_key)],
)


# --- Schemas ---

class CreateEnvironmentRequest(BaseModel):
    """Spin up a new testing environment."""
    env_type: str = Field(
        default="pattern",
        description="Environment type: pattern, navigation, api_mock, adversarial.",
    )
    difficulty: str = Field(
        default="medium",
        description="Difficulty: easy, medium, hard, extreme.",
    )
    seed: int | None = Field(
        None,
        description="Random seed for reproducible environments.",
    )


class EnvironmentResponse(BaseModel):
    """Sandbox environment state (hidden rules are never exposed)."""
    env_id: str
    env_type: str
    difficulty: str
    description: str
    state: dict
    action_count: int = 0
    created_at: datetime
    completed_at: datetime | None = None


class ActionRequest(BaseModel):
    """Submit an action to the environment."""
    action: dict = Field(
        ...,
        description=(
            "Action to perform. Structure depends on environment type:\n"
            "- pattern: {type: 'submit_transform', value: 'rotate'}\n"
            "- navigation: {type: 'move', value: 3}\n"
            "- api_mock: {type: 'call_endpoint', value: '/api/v1/resource_0'}\n"
            "- adversarial: {type: 'choose', value: 'careful'}"
        ),
    )


class ActionResponse(BaseModel):
    """Result of an action in the environment."""
    step: int
    action_accepted: bool
    state_changed: bool
    feedback: str
    reward: float
    done: bool
    new_state: dict


class EvaluationResponse(BaseModel):
    """Final generalization score for a completed environment."""
    env_id: str
    env_type: str
    difficulty: str
    solved: bool
    steps_used: int
    max_steps: int
    efficiency: float
    raw_score: float
    generalization_score: float = Field(
        ..., description="0-100 score measuring the agent's ability to generalize."
    )
    action_count: int


class EnvironmentListResponse(BaseModel):
    environments: list[dict]
    total: int


# --- Endpoints ---

@router.post(
    "/environments",
    response_model=EnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a testing environment",
    description=(
        "Spin up a headless puzzle environment. The agent-under-test must "
        "discover hidden rules through interaction, not instruction.\n\n"
        "**Environment Types:**\n"
        "- **pattern** — Discover input→output transformation rules\n"
        "- **navigation** — Navigate a state graph to reach a goal\n"
        "- **api_mock** — Interact with a shifting mock API\n"
        "- **adversarial** — Environment actively tries to deceive"
    ),
)
async def create_environment(
    request: CreateEnvironmentRequest,
    engine: SandboxEngine = Depends(get_sandbox_engine),
):
    try:
        env = await engine.create_environment(
            env_type=request.env_type,
            difficulty=request.difficulty,
            seed=request.seed,
        )
        return _env_to_response(env, engine)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_config", "message": str(e)},
        )


@router.post(
    "/environments/{env_id}/actions",
    response_model=ActionResponse,
    summary="Submit an action to the environment",
    description=(
        "The agent-under-test submits an action, receives feedback and reward. "
        "No instructions are given — the agent must discover the rules."
    ),
)
async def submit_action(
    env_id: str,
    request: ActionRequest,
    engine: SandboxEngine = Depends(get_sandbox_engine),
):
    try:
        result = await engine.submit_action(env_id, request.action)
        return ActionResponse(
            step=result.step,
            action_accepted=result.action_accepted,
            state_changed=result.state_changed,
            feedback=result.feedback,
            reward=result.reward,
            done=result.done,
            new_state=result.new_state,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "environment_not_found", "message": str(e)},
        )


@router.post(
    "/environments/{env_id}/evaluate",
    response_model=EvaluationResponse,
    summary="Evaluate the agent's performance",
    description=(
        "Compute the final generalization score. Call this after the agent "
        "has finished interacting with the environment. Score components:\n\n"
        "- **Efficiency** (0-20): How quickly did the agent solve it?\n"
        "- **Solved bonus** (0-50): Did the agent actually solve it?\n"
        "- **Score bonus** (0-30): Cumulative reward from actions"
    ),
)
async def evaluate_environment(
    env_id: str,
    engine: SandboxEngine = Depends(get_sandbox_engine),
):
    try:
        result = await engine.evaluate(env_id)
        return EvaluationResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "environment_not_found", "message": str(e)},
        )


@router.get(
    "/environments/{env_id}",
    response_model=EnvironmentResponse,
    summary="Get environment state",
    description="Retrieve current state of a sandbox environment.",
)
async def get_environment(
    env_id: str,
    engine: SandboxEngine = Depends(get_sandbox_engine),
):
    env = await engine.get_environment(env_id)
    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "environment_not_found"},
        )
    return _env_to_response(env, engine)


@router.get(
    "/environments",
    response_model=EnvironmentListResponse,
    summary="List all environments",
)
async def list_environments(
    engine: SandboxEngine = Depends(get_sandbox_engine),
):
    envs = await engine.list_environments()
    return EnvironmentListResponse(
        environments=[
            {
                "env_id": e.env_id,
                "env_type": e.env_type.value,
                "difficulty": e.difficulty.value,
                "steps_used": e.state.step,
                "solved": e.state.solved,
                "created_at": e.created_at,
            }
            for e in envs
        ],
        total=len(envs),
    )


def _env_to_response(env, engine: SandboxEngine) -> EnvironmentResponse:
    return EnvironmentResponse(
        env_id=env.env_id,
        env_type=env.env_type.value,
        difficulty=env.difficulty.value,
        description=env.description,
        state=engine._safe_state(env),
        action_count=len(env.action_history),
        created_at=env.created_at,
        completed_at=env.completed_at,
    )
