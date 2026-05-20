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

from ..core.config import get_settings
from ..schemas.awi import AWIDiscoveryManifest, AWIRepresentationType
from ..services.awi_action_vocab import get_awi_vocabulary

router = APIRouter(prefix="", tags=["Agent Discovery"])

settings = get_settings()


def get_agent_first_metadata() -> dict[str, Any]:
    """
    Single source of truth for agent-first bootstrap hints.
    Used by /.well-known/agent.json and GET /v1/discover.
    """
    return {
        "primary_audience": "autonomous_agents",
        "design_principle": "agent_first",
        "bootstrap_sequence": [
            "/.well-known/agent.json",
            "/.well-known/awi.json",
            "/llm.txt",
            "/mcp/tools.json",
            "/openapi.json",
        ],
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
        default_factory=lambda: [
            "billing",
            "telemetry",
            "agent_communication",
            "ai_decision_making",
            "mcp_tools",
            "awi_automation",
            "sandbox_testing",
            "passkey_auth",
            "dom_bridge",
            "rag_memory",
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
            "phase9_passkey": "/v1/awi/passkey/register",
            "phase9_dom_bridge": "/v1/awi/dom/snapshot",
            "phase9_rag": "/v1/awi/rag/ingest",
        }
    )

    agent_first: dict[str, Any] = Field(
        default_factory=get_agent_first_metadata,
        description=(
            "How autonomous clients should treat this service: discovery order, "
            "authority for simulation vs real behavior."
        ),
    )


def _build_agent_manifest() -> AgentPluginManifest:
    """Build the agent plugin manifest."""
    return AgentPluginManifest(
        name="agent-middleware-api",
        description=(
            "Operational control plane for autonomous agents: identity, billing, "
            "discovery, policy, and execution governance for machine-native "
            "software tenants."
        ),
        version=settings.APP_VERSION,
        endpoints={
            "api_base": "/v1",
            "discovery": "/v1/discover",
            "mcp": "/mcp",
            "awi": "/v1/awi",
            "awi_passkey": "/v1/awi/passkey",
            "awi_dom": "/v1/awi/dom",
            "awi_rag": "/v1/awi/rag",
            "billing": "/v1/billing",
            "telemetry": "/v1/telemetry",
            "comms": "/v1/comms",
            "ai": "/v1/ai",
            "health": "/health",
            "agent_manifest": "/.well-known/agent.json",
            "llm_docs": "/llm.txt",
        },
    )


def build_awi_manifest() -> dict[str, Any]:
    """Build the AWI-over-MCP discovery manifest."""
    vocabulary = get_awi_vocabulary()
    actions = [action.to_public_dict() for action in vocabulary.list_all_actions()]

    return {
        "schema_version": "0.1.0",
        "awi_version": "0.1.0-draft",
        "status": "draft",
        "profile": "awi-over-mcp",
        "transport": {
            "primary": "http",
            "mcp_compatible": True,
            "mcp_manifest": "/.well-known/mcp/tools.json",
        },
        "description": (
            "Agentic Web Interface semantics exposed through the existing "
            "governed MCP/HTTP control plane."
        ),
        "endpoints": {
            "sessions": "/v1/awi/sessions",
            "execute": "/v1/awi/execute",
            "represent": "/v1/awi/represent",
            "intervene": "/v1/awi/intervene",
            "vocabulary": "/v1/awi/vocabulary",
            "queue_status": "/v1/awi/queue/status",
            "audit_events": "/v1/audit/events",
            "audit_chain_verification": "/v1/audit/verify-chain",
            "openapi": "/openapi.json",
        },
        "representation_types": [item.value for item in AWIRepresentationType],
        "actions": actions,
        "safety_capabilities": {
            "wallet_scoped_authorization": True,
            "human_intervention": ["pause", "resume", "steer"],
            "passkey_high_risk_actions": True,
            "signed_permits": True,
            "tamper_evident_audit_chain": True,
            "sensitive_parameter_redaction": True,
        },
        "known_limitations": [
            "This is an AWI semantics profile over MCP/HTTP, not a standalone AWI wire standard.",
            "The login action is provisional; credential_handle is preferred over plaintext credentials.",
            "click_button and scroll are compatibility actions, not pure semantic actions.",
            "Representation efficiency benchmarks are local and deterministic until external WebArena-style evaluation is added.",
        ],
    }


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
    "/.well-known/awi.json",
    response_model=AWIDiscoveryManifest,
    summary="AWI Discovery Manifest",
    description=(
        "Returns the draft AWI-over-MCP manifest with action vocabulary, "
        "representation types, endpoints, safety capabilities, and known limits."
    ),
)
async def get_awi_json():
    """Serve the draft AWI-over-MCP manifest."""
    return JSONResponse(content=build_awi_manifest(), media_type="application/json")


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
