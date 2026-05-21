"""Shared authorization helpers for agent communications routers."""

from fastapi import HTTPException, status

from ..core.auth import AuthContext
from ..services.agent_comms import AgentComms, RegisteredAgent


async def require_agent_owner(
    auth: AuthContext,
    comms: AgentComms,
    agent_id: str,
) -> RegisteredAgent:
    """Require that the authenticated caller owns the registered agent."""
    agent = await comms.registry.get(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "agent_not_found",
                "message": f"Agent '{agent_id}' was not found.",
            },
        )

    if auth.is_bootstrap_admin:
        return agent

    if agent.owner_key and agent.owner_key == auth.raw_key:
        return agent

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "access_denied",
            "message": "API key is not authorized for this agent.",
            "agent_id": agent_id,
        },
    )
