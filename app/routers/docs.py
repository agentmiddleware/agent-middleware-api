"""
LLM-Optimized Documentation Router
------------------------------------
Serves documentation in formats designed for agent consumption.
This is the new SEO: if an LLM can't parse your docs, agents won't
recommend your product.

Endpoints:
- /llm.txt — Canonical copy in ``static/llm.txt`` (served by ``app/routers/static.py``)
- /docs/index — Structured JSON doc index for agent navigation
- /.well-known/agent.json — Standard agent discovery manifest (``app/routers/well_known.py``)
"""

from fastapi import APIRouter

from ..core.config import get_settings
from .well_known import get_agent_first_metadata

router = APIRouter(
    tags=["Documentation & Discovery"],
)

_TRUST_PLANE_SECTIONS = [
    {
        "id": "agent_manifest",
        "title": "Agent plugin manifest",
        "path": "/.well-known/agent.json",
        "content_type": "application/json",
        "summary": ("Canonical bootstrap: capabilities, endpoints, and agent_first."),
    },
    {
        "id": "wedge",
        "title": "Product wedge",
        "path": "/WEDGE.md",
        "content_type": "text/markdown",
        "summary": "Exactly-once permits and receipts for metered MCP calls.",
    },
    {
        "id": "security_limitations",
        "title": "Security limitations",
        "path": "/SECURITY_LIMITATIONS.md",
        "content_type": "text/markdown",
        "summary": "Honest non-claims and required production posture.",
    },
    {
        "id": "partner_guide",
        "title": "Design partner guide",
        "path": "/DESIGN_PARTNER_GUIDE.md",
        "content_type": "text/markdown",
        "summary": "Demo + dogfood path (partner.notes.write locally).",
    },
    {
        "id": "overview",
        "title": "API Overview (llm.txt)",
        "path": "/llm.txt",
        "content_type": "text/plain",
        "summary": "Full API documentation in LLM-optimized plaintext format.",
    },
    {
        "id": "openapi",
        "title": "OpenAPI Specification",
        "path": "/openapi.json",
        "content_type": "application/json",
        "summary": (
            "Machine-readable OpenAPI 3.1 specification with all endpoints, "
            "schemas, and examples."
        ),
    },
    {
        "id": "interactive",
        "title": "Interactive API Explorer",
        "path": "/docs",
        "content_type": "text/html",
        "summary": (
            "Swagger UI for testing endpoints (primarily for human developers)."
        ),
    },
    {
        "id": "redoc",
        "title": "ReDoc Reference",
        "path": "/redoc",
        "content_type": "text/html",
        "summary": "Detailed API reference documentation.",
    },
]

_TRUST_PLANE_SERVICES = [
    {
        "id": "agent-billing",
        "name": "Wallet metering",
        "base_path": "/v1/billing",
        "surface": "product",
        "capabilities": [
            "sponsor-wallets",
            "agent-wallets",
            "per-action-micro-metering",
            "transaction-ledger",
            "daily-spend-limits",
        ],
        "quickstart_endpoint": "POST /v1/billing/wallets/sponsor",
    },
    {
        "id": "mcp-trust-plane",
        "name": "Governed MCP",
        "base_path": "/mcp",
        "surface": "product",
        "capabilities": [
            "tools-discovery",
            "permit-gated-invoke",
            "idempotent-retries",
            "signed-receipts",
        ],
        "quickstart_endpoint": "GET /mcp/tools.json",
    },
    {
        "id": "permits",
        "name": "Signed permits",
        "base_path": "/v1/permits",
        "surface": "product",
        "capabilities": ["scoped-permits", "revoke", "budget-binding"],
        "quickstart_endpoint": "POST /v1/permits",
    },
    {
        "id": "receipts",
        "name": "Signed receipts",
        "base_path": "/v1/receipts",
        "surface": "product",
        "capabilities": ["receipt-verify", "evidence-bundle"],
        "quickstart_endpoint": "GET /v1/receipts",
    },
    {
        "id": "audit",
        "name": "Wallet audit chain",
        "base_path": "/v1/audit",
        "surface": "product",
        "capabilities": ["tamper-evident-chain", "wallet-scoped-events"],
        "quickstart_endpoint": "GET /v1/audit/events",
    },
]

_PROOF_SURFACE_SERVICES = [
    {
        "id": "iot-bridge",
        "name": "IoT Protocol Bridge",
        "base_path": "/v1/iot",
        "surface": "proof_surface",
        "capabilities": [
            "device-registration",
            "protocol-translation",
            "topic-acl-enforcement",
        ],
        "quickstart_endpoint": "POST /v1/iot/devices",
    },
    {
        "id": "autonomous-pm",
        "name": "Autonomous Product Manager",
        "base_path": "/v1/telemetry",
        "surface": "proof_surface",
        "capabilities": [
            "telemetry-ingestion",
            "anomaly-detection",
            "auto-pr-generation",
        ],
        "quickstart_endpoint": "POST /v1/telemetry/events",
    },
    {
        "id": "media-engine",
        "name": "Programmatic Media Engine",
        "base_path": "/v1/media",
        "surface": "proof_surface",
        "capabilities": ["video-ingestion", "viral-hook-detection"],
        "quickstart_endpoint": "POST /v1/media/videos",
    },
    {
        "id": "agent-comms",
        "name": "Agent Communications",
        "base_path": "/v1/comms",
        "surface": "proof_surface",
        "capabilities": ["agent-messaging", "capability-discovery"],
        "quickstart_endpoint": "POST /v1/comms/agents",
    },
]


@router.get(
    "/docs/index",
    summary="Structured documentation index",
    description=(
        "Returns a JSON index of documentation resources. Trust-plane sections "
        "always; proof-surface service entries only when mounted."
    ),
)
async def get_doc_index():
    services = list(_TRUST_PLANE_SERVICES)
    if get_settings().ENABLE_PROOF_SURFACES:
        services.extend(_PROOF_SURFACE_SERVICES)

    return {
        "agent_first": get_agent_first_metadata(),
        "version": "0.2.0",
        "format": "agent-native-docs/v1",
        "product_wedge": "governed_mcp_trust_plane",
        "last_updated": "2026-08-03",
        "sections": list(_TRUST_PLANE_SECTIONS),
        "services": services,
        "auth": {
            "method": "api_key",
            "header": "X-API-Key",
            "docs": "/llm.txt#authentication",
        },
        "note": (
            "Not a full agent middleware platform. Proof-surface services appear "
            "only when ENABLE_PROOF_SURFACES=true."
        ),
    }
