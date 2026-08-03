"""
Agent Discovery Router — Phase 9
================================
Machine-readable discovery endpoints for autonomous agents.

Provides standardized endpoints that agents crawl first to discover
capabilities, tools, pricing, and how to integrate.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Any, Optional

from ..core.auth import verify_api_key
from ..core.config import get_settings
from .well_known import get_agent_first_metadata

router = APIRouter(
    prefix="/v1",
    tags=["Agent Discovery"],
)

settings = get_settings()


class ServiceCapability(BaseModel):
    name: str
    version: str
    description: str
    category: str
    requires_auth: bool = True
    surface: str = Field(
        default="product",
        description=(
            "'product' = MCP trust-plane wedge; 'proof_surface' = labeled "
            "demo/workload scaffolding (often simulated)."
        ),
    )
    simulation_default: bool | None = Field(
        default=None,
        description="When true, this surface defaults to simulation mode.",
    )


class MCPToolInfo(BaseModel):
    service_id: str
    name: str
    description: str
    category: str
    credits_per_call: float
    unit_name: str


class AWIEndpoint(BaseModel):
    path: str
    method: str
    description: str
    action_type: Optional[str] = None


class PricingTier(BaseModel):
    tier_name: str
    price_per_credit: float
    minimum_purchase: float
    features: list[str]


class DiscoveryManifest(BaseModel):
    name: str = Field(description="Service name")
    version: str = Field(description="API version")
    description: str = Field(description="What this service provides")

    capabilities: list[ServiceCapability] = Field(
        default_factory=list, description="List of service capabilities"
    )

    mcp_tools: list[MCPToolInfo] = Field(
        default_factory=list, description="Available MCP tools"
    )

    awi_endpoints: list[AWIEndpoint] = Field(
        default_factory=list, description="AWI (Agentic Web Interface) endpoints"
    )

    pricing: list[PricingTier] = Field(
        default_factory=list, description="Pricing tiers"
    )

    authentication: dict = Field(
        default_factory=lambda: {
            "method": "api_key",
            "header": "X-API-Key",
            "format": "string",
        }
    )

    rate_limits: dict = Field(
        default_factory=lambda: {"requests_per_minute": 120, "burst_allowance": 20}
    )

    documentation: dict = Field(
        default_factory=lambda: {
            "openapi": "/openapi.json",
            "interactive_docs": "/docs",
            "llm_readable": "/llm.txt",
            "agent_manifest": "/.well-known/agent.json",
            "wedge": "/WEDGE.md",
            "security_limitations": "/SECURITY_LIMITATIONS.md",
            "partner_guide": "/DESIGN_PARTNER_GUIDE.md",
        }
    )

    integration_guides: dict = Field(
        default_factory=dict,
        description="Integration entry points; proof-surface guides only when mounted.",
    )

    agent_first: dict[str, Any] = Field(
        default_factory=get_agent_first_metadata,
        description=(
            "Same metadata as /.well-known/agent.json agent_first: "
            "bootstrap order and where to read simulation vs real state."
        ),
    )


def _build_capabilities() -> list[ServiceCapability]:
    """Build the list of service capabilities with product vs proof labels."""
    product = [
        ServiceCapability(
            name="billing",
            version="1.0",
            description=(
                "Wallet metering with ledger charges used by governed MCP invokes"
            ),
            category="financial",
            surface="product",
        ),
        ServiceCapability(
            name="mcp",
            version="1.0",
            description=(
                "Governed Model Context Protocol: permit validation, metering, "
                "signed receipts, and audit"
            ),
            category="tooling",
            surface="product",
        ),
        ServiceCapability(
            name="permits",
            version="1.0",
            description="Scoped signed permits for tool, wallet, budget, and expiry",
            category="authorization",
            surface="product",
        ),
        ServiceCapability(
            name="receipts",
            version="1.0",
            description="Signed receipts for governed tool attempts",
            category="evidence",
            surface="product",
        ),
        ServiceCapability(
            name="audit",
            version="1.0",
            description="Wallet-scoped tamper-evident audit chain",
            category="governance",
            surface="product",
        ),
        ServiceCapability(
            name="policies",
            version="1.0",
            description="Policy bundles evaluated on governed invocations",
            category="governance",
            surface="product",
        ),
        ServiceCapability(
            name="api_keys",
            version="1.0",
            description="Wallet-scoped API key issuance and rotation",
            category="security",
            surface="product",
        ),
        ServiceCapability(
            name="kyc",
            version="1.0",
            description="Stripe Identity KYC verification for sponsor wallets",
            category="compliance",
            surface="product",
        ),
    ]

    proof = [
        ServiceCapability(
            name="telemetry",
            version="1.0",
            description="Emit events, detect anomalies, and trigger autonomous responses",
            category="observability",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="comms",
            version="1.0",
            description="Agent-to-agent messaging (webhook delivery simulated by default)",
            category="communication",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="ai",
            version="1.0",
            description="AI-powered decision making, self-healing, and memory demos",
            category="intelligence",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="awi",
            version="1.0",
            description=(
                "Agentic Web Interface proof surface — not permit-enforced on HTTP "
                "unless routed through governed MCP"
            ),
            category="automation",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="sandbox",
            version="1.0",
            description="Dry-run and behavioral sandbox demos (not production isolation)",
            category="testing",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="iot",
            version="1.0",
            description="IoT protocol bridge (MQTT/CoAP simulated by default)",
            category="iot",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="passkey",
            version="1.0",
            description=(
                "FIDO2/WebAuthn for high-risk AWI actions; mock path refused in "
                "production-like environments"
            ),
            category="security",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="dom_bridge",
            version="1.0",
            description="Playwright DOM↔AWI bridge proof surface",
            category="automation",
            surface="proof_surface",
            simulation_default=True,
        ),
        ServiceCapability(
            name="rag_memory",
            version="1.0",
            description="Semantic memory over AWI sessions (may use mock embeddings)",
            category="intelligence",
            surface="proof_surface",
            simulation_default=True,
        ),
    ]

    if get_settings().ENABLE_PROOF_SURFACES:
        return product + proof
    return product


def _build_mcp_tools() -> list[MCPToolInfo]:
    """Build the list of available MCP tools for the discover catalog.

    When proof surfaces are off, return an empty catalog and point agents at
    ``/mcp/tools.json`` (ops-registered / dogfood tools only).
    """
    if not get_settings().ENABLE_PROOF_SURFACES:
        return []

    return [
        MCPToolInfo(
            service_id="telemetry",
            name="emit_telemetry_event",
            description="Emit a telemetry event with custom properties",
            category="observability",
            credits_per_call=1.0,
            unit_name="event",
        ),
        MCPToolInfo(
            service_id="billing",
            name="charge_wallet",
            description="Deduct credits from a wallet",
            category="financial",
            credits_per_call=1.0,
            unit_name="transaction",
        ),
        MCPToolInfo(
            service_id="comms",
            name="send_agent_message",
            description="Send a message to another agent",
            category="communication",
            credits_per_call=1.0,
            unit_name="message",
        ),
        MCPToolInfo(
            service_id="ai",
            name="decide",
            description="Use AI to make autonomous decisions",
            category="intelligence",
            credits_per_call=10.0,
            unit_name="decision",
        ),
        MCPToolInfo(
            service_id="ai",
            name="heal",
            description="AI-powered self-healing diagnostics",
            category="intelligence",
            credits_per_call=15.0,
            unit_name="diagnosis",
        ),
        MCPToolInfo(
            service_id="awi",
            name="create_session",
            description="Create an AWI session for web automation",
            category="automation",
            credits_per_call=5.0,
            unit_name="session",
        ),
        MCPToolInfo(
            service_id="passkey",
            name="create_passkey_challenge",
            description="Create WebAuthn challenge for high-risk action verification (checkout, payment, etc.)",
            category="security",
            credits_per_call=2.0,
            unit_name="challenge",
        ),
        MCPToolInfo(
            service_id="passkey",
            name="verify_passkey",
            description="Verify WebAuthn credential response from biometric authentication",
            category="security",
            credits_per_call=1.0,
            unit_name="verification",
        ),
        MCPToolInfo(
            service_id="dom_bridge",
            name="create_dom_session",
            description="Create browser session for DOM automation via Playwright",
            category="automation",
            credits_per_call=5.0,
            unit_name="session",
        ),
        MCPToolInfo(
            service_id="dom_bridge",
            name="sync_dom_action",
            description="Execute AWI action via real browser DOM",
            category="automation",
            credits_per_call=3.0,
            unit_name="action",
        ),
        MCPToolInfo(
            service_id="rag_memory",
            name="query_memories",
            description="Semantic search over past AWI session memories",
            category="intelligence",
            credits_per_call=2.0,
            unit_name="query",
        ),
        MCPToolInfo(
            service_id="rag_memory",
            name="get_session_context",
            description="Get relevant context from past sessions for current session",
            category="intelligence",
            credits_per_call=2.0,
            unit_name="context",
        ),
    ]


def _build_awi_endpoints() -> list[AWIEndpoint]:
    """Build the list of AWI endpoints."""
    return [
        AWIEndpoint(
            path="/v1/awi/sessions",
            method="POST",
            description="Create a stateful AWI session",
            action_type="session_management",
        ),
        AWIEndpoint(
            path="/v1/awi/execute",
            method="POST",
            description="Execute standardized higher-level actions",
            action_type="action_execution",
        ),
        AWIEndpoint(
            path="/v1/awi/represent",
            method="POST",
            description="Get progressive representations (summary, embedding, full)",
            action_type="representation",
        ),
        AWIEndpoint(
            path="/v1/awi/intervene",
            method="POST",
            description="Human pause/steer for agentic task queues",
            action_type="human_oversight",
        ),
        AWIEndpoint(
            path="/v1/awi/queue/status",
            method="GET",
            description="Check task queue status",
            action_type="queue_management",
        ),
        AWIEndpoint(
            path="/v1/awi/vocabulary",
            method="GET",
            description="Get the AWI action vocabulary",
            action_type="discovery",
        ),
        AWIEndpoint(
            path="/v1/awi/passkey/challenge",
            method="POST",
            description="Create WebAuthn challenge for high-risk action verification",
            action_type="security",
        ),
        AWIEndpoint(
            path="/v1/awi/passkey/verify",
            method="POST",
            description="Verify WebAuthn credential response",
            action_type="security",
        ),
        AWIEndpoint(
            path="/v1/awi/passkey/status/{session_id}/{action}",
            method="GET",
            description="Check passkey verification status",
            action_type="security",
        ),
        AWIEndpoint(
            path="/v1/awi/dom/session",
            method="POST",
            description="Create browser session for DOM automation",
            action_type="browser_automation",
        ),
        AWIEndpoint(
            path="/v1/awi/dom/sync",
            method="POST",
            description="Execute AWI action via Playwright",
            action_type="browser_automation",
        ),
        AWIEndpoint(
            path="/v1/awi/dom/state/{session_id}",
            method="GET",
            description="Get DOM state as AWI representation",
            action_type="browser_automation",
        ),
        AWIEndpoint(
            path="/v1/awi/rag/index",
            method="POST",
            description="Index AWI session for semantic retrieval",
            action_type="memory",
        ),
        AWIEndpoint(
            path="/v1/awi/rag/query",
            method="POST",
            description="Semantic search over session memories",
            action_type="memory",
        ),
        AWIEndpoint(
            path="/v1/awi/rag/context/{session_id}",
            method="GET",
            description="Get context from past sessions",
            action_type="memory",
        ),
    ]


def _build_pricing() -> list[PricingTier]:
    """Build pricing tiers for the trust-plane wedge (not proof surfaces)."""
    return [
        PricingTier(
            tier_name="self_hosted",
            price_per_credit=0.0,
            minimum_purchase=0.0,
            features=[
                "Scoped signed permits",
                "Governed MCP invoke + metering",
                "Signed receipts + wallet audit",
            ],
        ),
        PricingTier(
            tier_name="design_partner",
            price_per_credit=0.001,
            minimum_purchase=10.0,
            features=[
                "Same trust loop as self-hosted",
                "One partner-registered MCP tool",
                "Operator runbook + dogfood path",
            ],
        ),
        PricingTier(
            tier_name="enterprise",
            price_per_credit=0.0008,
            minimum_purchase=1000.0,
            features=[
                "Wallet-scoped multi-tenant isolation",
                "Custom MCP tool registration",
                "Dedicated support (when contracted)",
            ],
        ),
    ]


def _build_integration_guides() -> dict[str, str]:
    """Trust-plane guides; AWI guide only when proof surfaces are mounted."""
    guides = {
        "mcp_server": "/mcp",
        "llm_txt": "/llm.txt",
        "wedge": "/WEDGE.md",
        "partner_guide": "/DESIGN_PARTNER_GUIDE.md",
        "dogfood": "make dogfood-trust-plane (local partner.notes.write)",
    }
    if get_settings().ENABLE_PROOF_SURFACES:
        guides["awi_adoption"] = "/docs/awi-adoption-guide.md"
    return guides


@router.get(
    "/discover",
    response_model=DiscoveryManifest,
    summary="Agent Discovery Manifest",
    description=(
        "Aggregated capability index: services, MCP tools, AWI endpoints, and "
        "pricing. Bootstrap order is defined in `/.well-known/agent.json` under "
        "`agent_first.bootstrap_sequence` (this endpoint is optional after those "
        "hints)."
    ),
)
async def get_discovery_manifest():
    """
    Aggregated discovery manifest for autonomous agents.

    Prefer `GET /.well-known/agent.json` first for `agent_first` metadata, then
    this payload for a fuller catalog when needed.
    """
    return DiscoveryManifest(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Governed MCP trust plane for autonomous agents: scoped permits, "
            "metered tool invocation, signed receipts, and wallet audit chains. "
            "Capabilities with surface=proof_surface are labeled scaffolding."
        ),
        capabilities=_build_capabilities(),
        mcp_tools=_build_mcp_tools(),
        awi_endpoints=_build_awi_endpoints()
        if get_settings().ENABLE_PROOF_SURFACES
        else [],
        pricing=_build_pricing(),
        integration_guides=_build_integration_guides(),
    )


@router.get(
    "/discover/tools",
    summary="List Available MCP Tools",
    description="Returns all available MCP tools with their schemas and pricing.",
)
async def list_mcp_tools(api_key: str = Depends(verify_api_key)):
    """
    List all MCP tools available for this API key.

    Tools are returned with full schema definitions suitable for
    direct use with MCP clients.
    """
    return {
        "tools": _build_mcp_tools(),
        "total": len(_build_mcp_tools()),
        "mcp_endpoint": "/mcp",
        "mcp_tools_json": "/mcp/tools.json",
    }


@router.get(
    "/discover/awi",
    summary="List AWI Endpoints",
    description="Returns all Agentic Web Interface endpoints and the action vocabulary.",
)
async def list_awi_endpoints(api_key: str = Depends(verify_api_key)):
    """
    List all AWI endpoints and the action vocabulary.

    This enables agents to understand:
    - How to create AWI sessions
    - What actions are available
    - How to request different representations
    - How to implement human pause/steer
    """
    if not get_settings().ENABLE_PROOF_SURFACES:
        return {
            "endpoints": [],
            "mounted": False,
            "note": "AWI is a proof surface and is not mounted (ENABLE_PROOF_SURFACES=false).",
            "mcp_tools_json": "/mcp/tools.json",
        }
    return {
        "endpoints": _build_awi_endpoints(),
        "vocabulary_endpoint": "/v1/awi/vocabulary",
        "reference": "/docs/awi-adoption-guide.md",
        "note": "AWI is a labeled proof surface, not the product wedge.",
    }
