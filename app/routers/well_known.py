"""
Agent Well-Known Router — Phase 9
=================================
Standard agent discovery endpoints following common conventions.

Implements /.well-known/agent.json for agent directory registration.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.api_surface import proof_surfaces_enabled
from ..core.config import get_settings

router = APIRouter(prefix="", tags=["Agent Discovery"])

settings = get_settings()


def _core_capabilities() -> list[str]:
    return [
        "billing",
        "agent_communication",
        "mcp_tools",
        "signed_permits",
        "signed_receipts",
        "wallet_scoped_api_keys",
        "tamper_evident_audit",
        "trust_readiness",
    ]


def _proof_capabilities() -> list[str]:
    return [
        "telemetry",
        "ai_decision_making",
        "awi_automation",
        "sandbox_testing",
        "passkey_auth",
        "dom_bridge",
        "rag_memory",
    ]


def _manifest_capabilities() -> list[str]:
    capabilities = _core_capabilities()
    if proof_surfaces_enabled(settings):
        capabilities.extend(_proof_capabilities())
    return capabilities


def _documentation_links() -> dict[str, str]:
    docs = {
        "api_reference": "/docs",
        "openapi": "/openapi.json",
        "llm_readable": "/llm.txt",
        "agent_recipes": "/docs/agent-recipes.md",
    }
    if proof_surfaces_enabled(settings):
        docs.update(
            {
                "awi_guide": "/docs/awi-adoption-guide.md",
                "phase9_passkey": "/v1/awi/passkey/register",
                "phase9_dom_bridge": "/v1/awi/dom/snapshot",
                "phase9_rag": "/v1/awi/rag/ingest",
            }
        )
    return docs


def get_agent_first_metadata() -> dict[str, Any]:
    """
    Single source of truth for agent-first bootstrap hints.
    Used by /.well-known/agent.json and GET /v1/discover.
    """
    bootstrap_sequence = [
        "/.well-known/agent.json",
        "/llm.txt",
        "/mcp/tools.json",
        "/openapi.json",
    ]
    if proof_surfaces_enabled(settings):
        bootstrap_sequence.insert(1, "/.well-known/awi.json")

    return {
        "primary_audience": "autonomous_agents",
        "design_principle": "agent_first",
        "bootstrap_sequence": bootstrap_sequence,
        "simulation_and_dependency_truth": "/health/dependencies",
    }


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
        default_factory=_manifest_capabilities,
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

    documentation: dict = Field(default_factory=_documentation_links)

    agent_first: dict[str, Any] = Field(
        default_factory=get_agent_first_metadata,
        description=(
            "How autonomous clients should treat this service: discovery order, "
            "authority for simulation vs real behavior."
        ),
    )


def _build_agent_manifest() -> AgentPluginManifest:
    """Build the agent plugin manifest."""
    endpoints = {
        "api_base": "/v1",
        "discovery": "/v1/discover",
        "mcp": "/mcp",
        "billing": "/v1/billing",
        "health": "/health",
        "agent_manifest": "/.well-known/agent.json",
        "llm_docs": "/llm.txt",
    }
    if proof_surfaces_enabled(settings):
        endpoints.update(
            {
                "awi": "/v1/awi",
                "awi_passkey": "/v1/awi/passkey",
                "awi_dom": "/v1/awi/dom",
                "awi_rag": "/v1/awi/rag",
                "telemetry": "/v1/telemetry",
                "comms": "/v1/comms",
                "ai": "/v1/ai",
            }
        )

    return AgentPluginManifest(
        name="agent-middleware-api",
        description=(
            "Operational control plane for autonomous agents: identity, billing, "
            "discovery, policy, and execution governance for machine-native "
            "software tenants."
        ),
        version=settings.APP_VERSION,
        capabilities=_manifest_capabilities(),
        documentation=_documentation_links(),
        endpoints=endpoints,
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
    from .mcp import build_mcp_tools_manifest

    return JSONResponse(content=await build_mcp_tools_manifest())
