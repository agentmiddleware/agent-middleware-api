"""
Agent Well-Known Router — Phase 9
=================================
Standard agent discovery endpoints following common conventions.

Implements /.well-known/agent.json for agent directory registration.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from ..core.config import get_settings

router = APIRouter(prefix="", tags=["Agent Discovery"])

settings = get_settings()


class AgentPluginManifest(BaseModel):
    """Standard agent plugin manifest format."""

    schema_version: str = Field(default="1.0", description="Manifest schema version")
    name: str = Field(description="Service/plugin name")
    description: str = Field(description="What this service provides")
    version: str = Field(description="Current version")
    provider: dict = Field(
        default_factory=lambda: {
            "name": "Agent-Native Middleware",
            "website": "https://github.com/PetrefiedThunder/agent-middleware-api",
        }
    )

    capabilities: list[str] = Field(
        default_factory=lambda: [
            "billing",
            "telemetry",
            "agent_communication",
            "ai_decision_making",
            "mcp_tools",
            "awi_automation",
            "sandbox_testing",
        ],
        description="List of capability identifiers",
    )

    endpoints: dict = Field(description="API endpoints")

    authentication: dict = Field(
        default_factory=lambda: {
            "type": "api_key",
            "header": "X-API-Key",
        }
    )

    pricing: dict = Field(
        default_factory=lambda: {
            "model": "credit_based",
            "free_tier": "1000 credits/month",
            "credit_conversion": "$0.001 per credit",
        }
    )

    integrations: dict = Field(
        default_factory=lambda: {
            "python_sdk": "pip install b2a-sdk",
            "typescript_sdk": "npm install @b2a/sdk",
            "mcp": True,
            "langgraph": True,
            "crewai": True,
            "autogen": True,
            "llamaindex": True,
        }
    )

    documentation: dict = Field(
        default_factory=lambda: {
            "api_reference": "/docs",
            "openapi": "/openapi.json",
            "llm_readable": "/llm.txt",
            "awi_guide": "/docs/awi-adoption-guide.md",
            "agent_recipes": "/docs/agent-recipes.md",
        }
    )


def _build_agent_manifest() -> AgentPluginManifest:
    """Build the agent plugin manifest."""
    return AgentPluginManifest(
        name="agent-middleware-api",
        description=(
            "The first open-source MCP + AWI control plane. "
            "Provides billing, telemetry, agent communication, AI decision making, "
            "and Agentic Web Interface automation for autonomous agents."
        ),
        version=settings.APP_VERSION,
        endpoints={
            "api_base": "/v1",
            "discovery": "/v1/discover",
            "mcp": "/mcp",
            "awi": "/v1/awi",
            "billing": "/v1/billing",
            "telemetry": "/v1/telemetry",
            "comms": "/v1/comms",
            "ai": "/v1/ai",
            "health": "/health",
        },
    )


@router.get(
    "/.well-known/agent.json",
    summary="Agent Plugin Manifest",
    description=(
        "Returns a standard agent plugin manifest for agent directories "
        "and plugin registries. This is how autonomous agents discover "
        "and evaluate this service."
    ),
    responses={
        200: {"description": "Agent plugin manifest"},
    },
)
async def get_agent_json(request: Request):
    """
    Serve the agent.json manifest.

    This follows the standard /.well-known/agent.json convention
    used by agent frameworks and directories.
    """
    manifest = _build_agent_manifest()
    return JSONResponse(
        content=manifest.model_dump(mode="json"),
        media_type="application/json",
    )


@router.get(
    "/.well-known/mcp/tools.json",
    summary="MCP Tools Manifest",
    description="Returns the MCP tools manifest for tool discovery.",
)
async def get_mcp_tools_json():
    """
    Serve the MCP tools manifest.

    This is the standard endpoint MCP clients use to discover
    available tools.
    """
    from .discover import _build_mcp_tools

    return JSONResponse(
        content={
            "tools": [_build_mcp_tools()[0].model_dump()],  # Placeholder
            "count": len(_build_mcp_tools()),
        }
    )
