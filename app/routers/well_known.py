"""
Agent Well-Known Router — Phase 9
=================================
Standard agent discovery endpoints following common conventions.

Implements /.well-known/agent.json for agent directory registration.
Product capabilities are the MCP trust-plane wedge; AWI and related
workloads are labeled proof surfaces (often simulated) and must not be
read as production-complete features.
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

# Trust-plane product capabilities (governed MCP wedge).
PRODUCT_CAPABILITIES: list[str] = [
    "billing",
    "mcp_tools",
    "permits",
    "receipts",
    "audit",
    "policies",
    "signing_keys",
    "api_keys",
]

# Proof-surface catalog — present for discovery honesty, not as product claims.
PROOF_SURFACE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "awi_automation",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": (
            "HTTP AWI routes bypass the permit→receipt loop unless invoked "
            "as governed MCP tools."
        ),
    },
    {
        "id": "passkey_auth",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": (
            "WebAuthn may use WEBAUTHN_ALLOW_MOCK in tests; production-like "
            "boots refuse mock verification."
        ),
    },
    {
        "id": "dom_bridge",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Playwright DOM bridge is a proof surface, not a production isolation boundary.",
    },
    {
        "id": "rag_memory",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Embeddings may fall back to mock vectors when no embedding provider is configured.",
    },
    {
        "id": "telemetry",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Autonomous PM / auto-PR paths are simulation-gated by default.",
    },
    {
        "id": "agent_communication",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Webhook delivery is simulated until SIMULATION_MODE_AGENT_COMMS is flipped with a real client.",
    },
    {
        "id": "sandbox_testing",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Sandboxes are dry-run / demo surfaces, not compliance isolation.",
    },
    {
        "id": "ai_decision_making",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "AI decide/heal endpoints are proof surfaces adjacent to the trust wedge.",
    },
]


def get_agent_first_metadata() -> dict[str, Any]:
    """
    Single source of truth for agent-first bootstrap hints.
    Used by /.well-known/agent.json and GET /v1/discover.
    """
    bootstrap = [
        "/.well-known/agent.json",
        "/llm.txt",
        "/mcp/tools.json",
        "/openapi.json",
    ]
    if settings.ENABLE_PROOF_SURFACES:
        # Insert AWI manifest after agent.json when proof surfaces are mounted.
        bootstrap.insert(1, "/.well-known/awi.json")

    return {
        "primary_audience": "autonomous_agents",
        "design_principle": "agent_first",
        "product_wedge": "governed_mcp_trust_plane",
        "product_loop": [
            "discover",
            "authenticate",
            "authorize",
            "invoke",
            "meter",
            "receipt",
            "audit",
            "govern",
        ],
        "bootstrap_sequence": bootstrap,
        "simulation_and_dependency_truth": "/health/dependencies",
        "proof_surfaces_enabled": bool(settings.ENABLE_PROOF_SURFACES),
        "proof_surface_note": (
            "Entries under proof_surfaces are demo/workload scaffolding. "
            "They do not define the product unless they consume the same "
            "permit, receipt, idempotency, and audit primitives via governed MCP."
        ),
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
        default_factory=lambda: list(PRODUCT_CAPABILITIES),
        description=(
            "Trust-plane product capability identifiers (MCP permit→meter→"
            "receipt→audit wedge). Proof surfaces are listed separately."
        ),
    )

    proof_surfaces: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Labeled non-product workloads. Treat as simulated/demo unless "
            "invoked through governed MCP with permits."
        ),
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
            "wedge": "/WEDGE.md",
            "security_limitations": "/SECURITY_LIMITATIONS.md",
            "agent_recipes": "/docs/agent-recipes.md",
        }
    )

    agent_first: dict[str, Any] = Field(
        default_factory=get_agent_first_metadata,
        description=(
            "How autonomous clients should treat this service: discovery order, "
            "authority for simulation vs real behavior, and product wedge scope."
        ),
    )


def _product_endpoints() -> dict[str, str]:
    return {
        "api_base": "/v1",
        "discovery": "/v1/discover",
        "mcp": "/mcp",
        "billing": "/v1/billing",
        "permits": "/v1/permits",
        "receipts": "/v1/receipts",
        "audit": "/v1/audit",
        "policies": "/v1/policies",
        "evidence": "/v1/evidence",
        "keys": "/v1/keys",
        "api_keys": "/v1/api-keys",
        "me": "/v1/me",
        "health": "/health",
        "agent_manifest": "/.well-known/agent.json",
        "llm_docs": "/llm.txt",
        "dependency_truth": "/health/dependencies",
    }


def _proof_surface_endpoints() -> dict[str, str]:
    return {
        "awi": "/v1/awi",
        "awi_passkey": "/v1/awi/passkey",
        "awi_dom": "/v1/awi/dom",
        "awi_rag": "/v1/awi/rag",
        "telemetry": "/v1/telemetry",
        "comms": "/v1/comms",
        "ai": "/v1/ai",
        "awi_manifest": "/.well-known/awi.json",
    }


def _build_agent_manifest() -> AgentPluginManifest:
    """Build the agent plugin manifest with honest product vs proof split."""
    endpoints = _product_endpoints()
    proof_surfaces = list(PROOF_SURFACE_CATALOG)
    documentation = {
        "api_reference": "/docs",
        "openapi": "/openapi.json",
        "llm_readable": "/llm.txt",
        "wedge": "/WEDGE.md",
        "security_limitations": "/SECURITY_LIMITATIONS.md",
        "agent_recipes": "/docs/agent-recipes.md",
    }

    if settings.ENABLE_PROOF_SURFACES:
        endpoints = {**endpoints, **_proof_surface_endpoints()}
        documentation = {
            **documentation,
            "awi_guide": "/docs/awi-adoption-guide.md",
            "phase9_passkey": "/v1/awi/passkey/register",
            "phase9_dom_bridge": "/v1/awi/dom/snapshot",
            "phase9_rag": "/v1/awi/rag/ingest",
        }
    else:
        proof_surfaces = [
            {
                **entry,
                "mounted": False,
                "note": (f"{entry['note']} Not mounted (ENABLE_PROOF_SURFACES=false)."),
            }
            for entry in proof_surfaces
        ]

    return AgentPluginManifest(
        name="agent-middleware-api",
        description=(
            "Governed MCP trust plane for autonomous agents: scoped permits, "
            "metered tool invocation, signed receipts, and wallet audit chains. "
            "Additional routers are labeled proof surfaces, not the product wedge."
        ),
        version=settings.APP_VERSION,
        capabilities=list(PRODUCT_CAPABILITIES),
        proof_surfaces=proof_surfaces,
        endpoints=endpoints,
        documentation=documentation,
        agent_first=get_agent_first_metadata(),
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
        "surface": "proof_surface",
        "transport": {
            "primary": "http",
            "mcp_compatible": True,
            "mcp_manifest": "/.well-known/mcp/tools.json",
        },
        "description": (
            "Proof-surface AWI semantics exposed beside the governed MCP "
            "trust plane. Prefer MCP tools with permits for metered, "
            "receipted automation."
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
            # Advertised as available on the proof surface; see known_limitations
            # for mock/production-like constraints and MCP-only permit path.
            "passkey_high_risk_actions": True,
            "signed_permits": True,
            "tamper_evident_audit_chain": True,
            "sensitive_parameter_redaction": True,
        },
        "known_limitations": [
            "This is an AWI semantics profile over MCP/HTTP, not a standalone AWI wire standard.",
            "HTTP AWI routes are a proof surface and do not enforce permits/receipts unless the call goes through governed MCP.",
            "Passkey verification fails closed without py_webauthn; WEBAUTHN_ALLOW_MOCK is refused in production-like environments.",
            "The login action is provisional; credential_handle is preferred over plaintext credentials.",
            "click_button and scroll are compatibility actions, not pure semantic actions.",
            "Representation efficiency benchmarks are local and deterministic until external WebArena-style evaluation is added.",
            "Sandbox and browser automation are not production isolation boundaries.",
        ],
    }


@router.get(
    "/.well-known/agent.json",
    summary="Agent Plugin Manifest",
    description=(
        "Returns a standard agent plugin manifest for agent directories "
        "and plugin registries. Product capabilities are the MCP trust "
        "plane; proof_surfaces are labeled demo/workload scaffolding."
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
        "representation types, endpoints, safety capabilities, and known limits. "
        "Marked as a proof surface — not the product wedge."
    ),
)
async def get_awi_json():
    """Serve the draft AWI-over-MCP manifest (only when proof surfaces are on)."""
    if not settings.ENABLE_PROOF_SURFACES:
        return JSONResponse(
            status_code=404,
            content={
                "error": "awi_manifest_unmounted",
                "detail": (
                    "AWI is a proof surface and is not mounted "
                    "(ENABLE_PROOF_SURFACES=false). Use /.well-known/agent.json "
                    "and /mcp/tools.json for the trust-plane wedge."
                ),
            },
        )
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
