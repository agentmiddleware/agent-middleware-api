"""
AWI Router — Phase 7
====================
Agentic Web Interface endpoints + MCP translation layer.

Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"

Provides standardized, stateful interfaces for web agents with:
- Higher-level unified actions (not DOM clicks)
- Progressive information transfer
- Agentic task queues with human pause/steer
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.auth import AuthContext, get_auth_context
from ..schemas.awi import (
    AWIHumanIntervention,
    AWIRepresentationRequest,
    AWIRepresentationResponse,
    AWIExecutionRequest,
    AWIExecutionResponse,
    AWISession,
    AWISessionCreate,
    AWITask,
    AWITaskCreate,
    AWITaskQueueStatus,
    AWIActionCategory,
)
from ..services.awi_action_vocab import get_awi_vocabulary
from ..services.awi_session import get_awi_session_manager
from ..services.awi_task_queue import get_awi_task_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/awi", tags=["AWI"])


async def _require_session_access(session_id: str, auth: AuthContext) -> AWISession:
    """Authorize access to an AWI session before exposing or mutating state."""
    manager = get_awi_session_manager()
    session = await manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Session {session_id} not found"},
        )

    if session.wallet_id:
        auth.require_wallet_access(session.wallet_id)
    else:
        auth.require_bootstrap_admin()

    return session


@router.post(
    "/sessions",
    response_model=AWISession,
    status_code=status.HTTP_201_CREATED,
    summary="Create AWI session",
    description=(
        "Create a stateful AWI session for agentic web interactions. "
        "Based on arXiv:2506.10953v1 - Stateful interfaces for web agents."
    ),
)
async def create_session(
    request: AWISessionCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Create a new Agentic Web Interface (AWI) session.

    Sessions provide stateful context for web agent interactions,
    enabling higher-level unified actions instead of raw DOM manipulation.
    """
    if request.wallet_id:
        auth.require_wallet_access(request.wallet_id)
    else:
        auth.require_bootstrap_admin()

    try:
        manager = get_awi_session_manager()
        return await manager.create_session(request)
    except Exception as e:
        logger.exception("Failed to create AWI session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "creation_failed", "message": str(e)},
        )


@router.get(
    "/sessions/{session_id}",
    summary="Get AWI session",
    description="Get the current state of an AWI session.",
)
async def get_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get the current state of an AWI session."""
    return await _require_session_access(session_id, auth)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Destroy AWI session",
    description="Destroy an AWI session and release resources.",
)
async def destroy_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Destroy an AWI session."""
    await _require_session_access(session_id, auth)
    manager = get_awi_session_manager()
    destroyed = await manager.destroy_session(session_id)

    if not destroyed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Session {session_id} not found"},
        )


@router.post(
    "/execute",
    response_model=AWIExecutionResponse,
    summary="Execute AWI action",
    description="Execute a standardized AWI action within a session.",
)
async def execute_action(
    request: AWIExecutionRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Execute a standardized AWI action.

    Actions use semantic vocabulary (search_and_sort, add_to_cart) instead
    of raw DOM manipulation, making agents more robust and website-independent.
    """
    try:
        await _require_session_access(request.session_id, auth)
        manager = get_awi_session_manager()
        return await manager.execute_action(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"AWI execution failed: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "execution_failed", "message": str(e)},
        )


@router.post(
    "/represent",
    response_model=AWIRepresentationResponse,
    summary="Request representation",
    description="Request a specific representation of the current session state.",
)
async def request_representation(
    request: AWIRepresentationRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Request a specific representation of the session state.

    Agents can request exactly the information they need (summary, embedding,
    low-res screenshot, etc.) instead of receiving full DOM every time.
    """
    try:
        await _require_session_access(request.session_id, auth)
        manager = get_awi_session_manager()
        result = await manager.request_representation(request)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Session {request.session_id} not found",
                },
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Representation request failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "representation_failed", "message": str(e)},
        )


@router.post(
    "/intervene",
    summary="Human intervention",
    description="Pause, resume, or steer an AWI session (human-in-the-loop).",
)
async def human_intervention(
    intervention: AWIHumanIntervention,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Human intervention in an AWI session.

    Allows humans to pause, resume, or steer agent actions for safety
    and alignment with human preferences.
    """
    try:
        await _require_session_access(intervention.session_id, auth)
        manager = get_awi_session_manager()
        return await manager.human_intervention(intervention)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Human intervention failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "intervention_failed", "message": str(e)},
        )


@router.get(
    "/vocabulary",
    summary="List AWI actions",
    description="List all standardized AWI actions.",
)
async def list_actions():
    """List all standardized AWI actions."""
    vocabulary = get_awi_vocabulary()
    actions = vocabulary.list_all_actions()

    return {
        "actions": [
            {
                "action": a.action.value,
                "category": a.category.value,
                "description": a.description,
                "parameters": a.parameters,
                "estimated_cost": a.estimated_cost,
            }
            for a in actions
        ],
        "categories": [c.value for c in AWIActionCategory],
    }


@router.get(
    "/vocabulary/category/{category}",
    summary="List actions by category",
    description="List AWI actions in a specific category.",
)
async def list_actions_by_category(category: AWIActionCategory):
    """List AWI actions by category."""
    vocabulary = get_awi_vocabulary()
    actions = vocabulary.list_actions_by_category(category)

    return {
        "category": category.value,
        "actions": [
            {
                "action": a.action.value,
                "description": a.description,
                "parameters": a.parameters,
                "estimated_cost": a.estimated_cost,
            }
            for a in actions
        ],
    }


@router.post(
    "/tasks",
    response_model=AWITask,
    status_code=status.HTTP_201_CREATED,
    summary="Create AWI task",
    description="Create a new AWI task in the queue.",
)
async def create_task(
    request: AWITaskCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    """Create a new AWI task in the queue."""
    auth.require_bootstrap_admin()
    try:
        queue = get_awi_task_queue()
        return await queue.create_task(request)
    except Exception as e:
        logger.exception("Failed to create AWI task")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "task_creation_failed", "message": str(e)},
        )


@router.get(
    "/tasks/{task_id}",
    summary="Get task status",
    description="Get the status of an AWI task.",
)
async def get_task(
    task_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get the status of an AWI task."""
    auth.require_bootstrap_admin()
    queue = get_awi_task_queue()
    task = await queue.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Task {task_id} not found"},
        )

    return task


@router.get(
    "/queue/status",
    response_model=AWITaskQueueStatus,
    summary="Get queue status",
    description="Get current status of the AWI task queue.",
)
async def get_queue_status(auth: AuthContext = Depends(get_auth_context)):
    """Get current status of the AWI task queue."""
    auth.require_bootstrap_admin()
    queue = get_awi_task_queue()
    return await queue.get_queue_status()


@router.post(
    "/queue/pause",
    summary="Global pause",
    description="Pause all tasks globally (human intervention).",
)
async def global_pause(
    reason: str | None = None,
    auth: AuthContext = Depends(get_auth_context),
):
    """Pause all AWI tasks globally."""
    auth.require_bootstrap_admin()
    queue = get_awi_task_queue()
    await queue.global_pause(reason)
    return {"success": True, "status": "paused", "reason": reason}


@router.post(
    "/queue/resume",
    summary="Global resume",
    description="Resume all AWI tasks after global pause.",
)
async def global_resume(auth: AuthContext = Depends(get_auth_context)):
    """Resume all AWI tasks after global pause."""
    auth.require_bootstrap_admin()
    queue = get_awi_task_queue()
    await queue.global_resume()
    return {"success": True, "status": "resumed"}
