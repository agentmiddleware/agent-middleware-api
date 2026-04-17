"""
Agent Discovery Router — Phase 9
================================
Machine-readable discovery endpoints for autonomous agents.

Provides standardized endpoints that agents crawl first to discover
capabilities, tools, pricing, and how to integrate.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

from ..core.auth import verify_api_key
from ..core.config import get_settings

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
        }
    )

    integration_guides: dict = Field(
        default_factory=lambda: {
            "python_sdk": "pip install b2a-sdk",
            "typescript_sdk": "npm install @b2a/sdk",
            "mcp_server": "/mcp",
            "awi_adoption": "/docs/awi-adoption-guide.md",
        }
    )


def _build_capabilities() -> list[ServiceCapability]:
    """Build the list of service capabilities."""
    return [
        ServiceCapability(
            name="billing",
            version="1.0",
            description="Two-tier wallet system with ACID transactions, Stripe integration, and spend velocity monitoring",
            category="financial",
        ),
        ServiceCapability(
            name="telemetry",
            version="1.0",
            description="Emit events, detect anomalies, and trigger autonomous responses",
            category="observability",
        ),
        ServiceCapability(
            name="comms",
            version="1.0",
            description="Agent-to-agent messaging, registration, and swarm coordination",
            category="communication",
        ),
        ServiceCapability(
            name="ai",
            version="1.0",
            description="AI-powered decision making, self-healing, natural language queries, and memory",
            category="intelligence",
        ),
        ServiceCapability(
            name="mcp",
            version="1.0",
            description="Model Context Protocol server for tool discovery and execution",
            category="tooling",
        ),
        ServiceCapability(
            name="awi",
            version="1.0",
            description="Agentic Web Interface - standardized web automation with human pause/steer",
            category="automation",
        ),
        ServiceCapability(
            name="sandbox",
            version="1.0",
            description="Dry-run sandbox and behavioral sandbox for safe tool testing",
            category="testing",
        ),
        ServiceCapability(
            name="kyc",
            version="1.0",
            description="Stripe Identity KYC verification for sponsor wallets",
            category="compliance",
        ),
        ServiceCapability(
            name="api_keys",
            version="1.0",
            description="Automated API key rotation and management",
            category="security",
        ),
        ServiceCapability(
            name="iot",
            version="1.0",
            description="Secure IoT protocol bridge with MQTT and CoAP support",
            category="iot",
        ),
    ]


def _build_mcp_tools() -> list[MCPToolInfo]:
    """Build the list of available MCP tools."""
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
    ]


def _build_pricing() -> list[PricingTier]:
    """Build pricing tiers."""
    return [
        PricingTier(
            tier_name="free",
            price_per_credit=0.0,
            minimum_purchase=0.0,
            features=[
                "1000 credits/month",
                "Basic telemetry",
                "Agent messaging",
            ],
        ),
        PricingTier(
            tier_name="pro",
            price_per_credit=0.001,
            minimum_purchase=10.0,
            features=[
                "Unlimited credits",
                "AI decision making",
                "AWI sessions",
                "Priority support",
            ],
        ),
        PricingTier(
            tier_name="enterprise",
            price_per_credit=0.0008,
            minimum_purchase=1000.0,
            features=[
                "Unlimited everything",
                "Custom MCP tools",
                "Multi-tenant isolation",
                "Dedicated support",
                "SLA guarantees",
            ],
        ),
    ]


@router.get(
    "/discover",
    response_model=DiscoveryManifest,
    summary="Agent Discovery Manifest",
    description=(
        "Returns a comprehensive machine-readable manifest of all services, "
        "MCP tools, AWI endpoints, and pricing. This is the primary endpoint "
        "for autonomous agents to discover and integrate with this platform."
    ),
)
async def get_discovery_manifest():
    """
    Primary discovery endpoint for autonomous agents.

    Returns a complete manifest including:
    - All service capabilities
    - Available MCP tools with pricing
    - AWI endpoints for web automation
    - Pricing tiers
    - Integration guides
    """
    return DiscoveryManifest(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Agent-native middleware platform - the first open-source MCP + AWI control plane",
        capabilities=_build_capabilities(),
        mcp_tools=_build_mcp_tools(),
        awi_endpoints=_build_awi_endpoints(),
        pricing=_build_pricing(),
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
    return {
        "endpoints": _build_awi_endpoints(),
        "vocabulary_endpoint": "/v1/awi/vocabulary",
        "reference": "/docs/awi-adoption-guide.md",
    }
