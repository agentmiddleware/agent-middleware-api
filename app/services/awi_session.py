"""
AWI Session Manager — Phase 7
=============================
Stateful AWI session manager that ties together actions, representations,
and task queues into cohesive agentic web interactions.

Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"

Provides:
- Stateful sessions with persistent context
- Action execution with vocabulary validation
- Progressive representation generation
- Human pause/steer capabilities
- Integration with MCP layer
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..schemas.awi import (
    AWIExecutionRequest,
    AWIExecutionResponse,
    AWIHumanIntervention,
    AWIRepresentationRequest,
    AWIRepresentationResponse,
    AWISession,
    AWISessionCreate,
    AWISessionStatus,
    AWIStandardAction,
)
from .awi_action_vocab import get_awi_vocabulary
from .awi_representation import get_awi_representation

logger = logging.getLogger(__name__)


class AWISessionManager:
    """
    Stateful AWI session manager.

    Based on the paper's principle: "Stateful interfaces (AWI)" -
    MCP is great but insufficient for web agents; they need stateful
    interfaces with persistent context.
    """

    def __init__(self):
        self._sessions: dict[str, AWISession] = {}
        self._session_state: dict[str, dict[str, Any]] = {}
        self._vocabulary = get_awi_vocabulary()
        self._representation = get_awi_representation()

    async def create_session(self, request: AWISessionCreate) -> AWISession:
        """Create a new AWI session."""
        session_id = f"awi-{uuid.uuid4().hex[:12]}"

        session = AWISession(
            session_id=session_id,
            target_url=request.target_url,
            status=AWISessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_url=request.target_url,
            max_steps=request.max_steps,
            human_pause_enabled=request.allow_human_pause,
            representation_history=[],
            action_history=[],
        )

        self._sessions[session_id] = session

        self._session_state[session_id] = {
            "target_url": request.target_url,
            "current_url": request.target_url,
            "cookies": {},
            "local_storage": {},
            "session_storage": {},
            "form_data": {},
            "capabilities": ["page_loaded"],
            "page_state": {
                "html": "<html><body>Initial page</body></html>",
                "title": request.target_url,
                "url": request.target_url,
                "elements": [],
            },
        }

        logger.info(f"Created AWI session: {session_id}")
        return session

    async def get_session(self, session_id: str) -> AWISession | None:
        """Get an existing session."""
        return self._sessions.get(session_id)

    async def execute_action(
        self, request: AWIExecutionRequest
    ) -> AWIExecutionResponse:
        """Execute an AWI action within a session."""
        session = self._sessions.get(request.session_id)
        if not session:
            return AWIExecutionResponse(
                execution_id=f"exec-{uuid.uuid4().hex[:12]}",
                session_id=request.session_id,
                action=request.action,
                status="error",
                parameters=request.parameters,
                error=f"Session not found: {request.session_id}",
            )

        if session.status == AWISessionStatus.PAUSED and session.paused_by_human:
            return AWIExecutionResponse(
                execution_id=f"exec-{uuid.uuid4().hex[:12]}",
                session_id=request.session_id,
                action=request.action,
                status="paused",
                parameters=request.parameters,
                error="Session is paused by human intervention",
            )

        if session.step_count >= session.max_steps:
            session.status = AWISessionStatus.COMPLETED
            return AWIExecutionResponse(
                execution_id=f"exec-{uuid.uuid4().hex[:12]}",
                session_id=request.session_id,
                action=request.action,
                status="max_steps_reached",
                parameters=request.parameters,
                error="Maximum steps reached",
            )

        execution_id = f"awi-exec-{uuid.uuid4().hex[:12]}"
        start_time = datetime.now(timezone.utc)

        is_valid, error = self._vocabulary.validate_parameters(
            request.action, request.parameters
        )
        if not is_valid:
            return AWIExecutionResponse(
                execution_id=execution_id,
                session_id=request.session_id,
                action=request.action,
                status="error",
                parameters=request.parameters,
                error=error,
            )

        state = self._session_state.get(request.session_id, {})
        preconditions_met, unmet = self._vocabulary.check_preconditions(
            request.action, state
        )

        if not preconditions_met and not request.dry_run:
            return AWIExecutionResponse(
                execution_id=execution_id,
                session_id=request.session_id,
                action=request.action,
                status="error",
                parameters=request.parameters,
                error=f"Preconditions not met: {unmet}",
            )

        # Phase 9: Check passkey requirement for high-risk actions
        from .webauthn_provider import get_webauthn_provider

        webauthn = get_webauthn_provider()

        if await webauthn.requires_passkey(request.session_id, request.action.value):
            if not await webauthn.is_action_verified(
                request.session_id, request.action.value
            ):
                return AWIExecutionResponse(
                    execution_id=execution_id,
                    session_id=request.session_id,
                    action=request.action,
                    status="passkey_required",
                    parameters=request.parameters,
                    error="This action requires biometric verification. "
                    "Call POST /v1/awi/passkey/challenge first.",
                )

        result = await self._execute_action_logic(
            request.action, request.parameters, state
        )

        session.action_history.append(
            {
                "execution_id": execution_id,
                "action": request.action.value,
                "parameters": request.parameters,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": result.get("success", True),
            }
        )

        session.step_count += 1
        session.updated_at = datetime.now(timezone.utc)
        session.status = AWISessionStatus.ACTIVE

        representation = None
        if request.representation_request:
            rep_result = await self._representation.generate_representation(
                request.session_id,
                request.representation_request,
                state.get("page_state", {}),
                {},
            )
            session.representation_history.append(rep_result)
            representation = rep_result

        duration_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )
        cost = self._vocabulary.get_estimated_cost(request.action)

        return AWIExecutionResponse(
            execution_id=execution_id,
            session_id=request.session_id,
            action=request.action,
            status="success",
            parameters=request.parameters,
            result=result,
            new_state=state,
            representation=representation,
            duration_ms=duration_ms,
            cost_estimate=cost if request.dry_run else None,
        )

    async def _execute_action_logic(
        self, action: AWIStandardAction, params: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute the logic for an AWI action."""
        if action == AWIStandardAction.NAVIGATE_TO:
            new_url = params.get("url", state.get("current_url"))
            state["current_url"] = new_url
            state["capabilities"].append("page_loaded")
            return {"success": True, "new_url": new_url}

        elif action == AWIStandardAction.SEARCH_AND_SORT:
            query = params.get("query", "")
            state["last_search"] = query
            state["last_sort"] = params.get("sort_by")
            return {
                "success": True,
                "results_count": 0,
                "items": [],
            }

        elif action == AWIStandardAction.FILL_FORM:
            fields = params.get("fields", {})
            state["form_data"].update(fields)
            return {"success": True, "fields_filled": len(fields)}

        elif action == AWIStandardAction.CLICK_BUTTON:
            button_id = params.get("button_id", params.get("button_text", ""))
            return {"success": True, "button_clicked": button_id}

        elif action == AWIStandardAction.GET_REPRESENTATION:
            return {
                "success": True,
                "representation_generated": True,
            }

        else:
            return {"success": True, "action": action.value}

    async def request_representation(
        self, request: AWIRepresentationRequest
    ) -> AWIRepresentationResponse | None:
        """Request a specific representation of the session state."""
        session = self._sessions.get(request.session_id)
        if not session:
            return None

        state = self._session_state.get(request.session_id, {})
        page_state = state.get("page_state", {})

        result = await self._representation.generate_representation(
            request.session_id,
            request.representation_type,
            page_state,
            request.options,
        )

        session.representation_history.append(result)

        return AWIRepresentationResponse(
            representation_id=result.get("representation_id", ""),
            session_id=request.session_id,
            representation_type=request.representation_type,
            content=result.get("content"),
            metadata=result.get("metadata", {}),
            generated_at=datetime.now(timezone.utc),
        )

    async def human_intervention(
        self, intervention: AWIHumanIntervention
    ) -> dict[str, Any]:
        """Handle human intervention in a session."""
        session = self._sessions.get(intervention.session_id)
        if not session:
            return {"success": False, "error": "Session not found"}

        if intervention.action == "pause":
            session.status = AWISessionStatus.PAUSED
            session.paused_by_human = True
            session.pause_reason = intervention.reason
            return {"success": True, "status": "paused"}

        elif intervention.action == "resume":
            session.status = AWISessionStatus.ACTIVE
            session.paused_by_human = False
            session.pause_reason = None
            return {"success": True, "status": "active"}

        elif intervention.action == "steer":
            if not intervention.steer_instructions:
                return {"success": False, "error": "No steering instructions provided"}
            session.action_history.append(
                {
                    "type": "human_steer",
                    "instructions": intervention.steer_instructions,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {
                "success": True,
                "status": "steered",
                "instructions_recorded": intervention.steer_instructions,
            }

        return {"success": False, "error": f"Unknown action: {intervention.action}"}

    async def destroy_session(self, session_id: str) -> bool:
        """Destroy an AWI session."""
        if session_id not in self._sessions:
            return False

        del self._sessions[session_id]
        if session_id in self._session_state:
            del self._session_state[session_id]

        logger.info(f"Destroyed AWI session: {session_id}")
        return True


_awi_session_manager: AWISessionManager | None = None


def get_awi_session_manager() -> AWISessionManager:
    """Get singleton AWI session manager instance."""
    global _awi_session_manager
    if _awi_session_manager is None:
        _awi_session_manager = AWISessionManager()
    return _awi_session_manager
