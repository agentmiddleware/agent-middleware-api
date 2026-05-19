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

from .well_known import get_agent_first_metadata

router = APIRouter(
    tags=["Documentation & Discovery"],
)


@router.get(
    "/docs/index",
    summary="Structured documentation index",
    description=(
        "Returns a JSON index of all available documentation resources. "
        "Agents use this to navigate the doc tree and find relevant sections "
        "without parsing the entire llm.txt."
    ),
)
async def get_doc_index():
    return {
        "agent_first": get_agent_first_metadata(),
        "version": "0.1.0",
        "format": "agent-native-docs/v1",
        "last_updated": "2026-02-22",
        "sections": [
            {
                "id": "agent_manifest",
                "title": "Agent plugin manifest",
                "path": "/.well-known/agent.json",
                "content_type": "application/json",
                "summary": (
                    "Canonical bootstrap: capabilities, endpoints, and agent_first."
                ),
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
        ],
        "services": [
            {
                "id": "iot-bridge",
                "name": "IoT Protocol Bridge",
                "base_path": "/v1/iot",
                "capabilities": [
                    "device-registration",
                    "protocol-translation",
                    "topic-acl-enforcement",
                    "mqtt-bridging",
                    "coap-bridging",
                    "device-subscription",
                ],
                "quickstart_endpoint": "POST /v1/iot/devices",
            },
            {
                "id": "autonomous-pm",
                "name": "Autonomous Product Manager",
                "base_path": "/v1/telemetry",
                "capabilities": [
                    "telemetry-ingestion",
                    "anomaly-detection",
                    "auto-pr-generation",
                    "error-analysis",
                    "llm-trace-analysis",
                ],
                "quickstart_endpoint": "POST /v1/telemetry/events",
            },
            {
                "id": "media-engine",
                "name": "Programmatic Media Engine",
                "base_path": "/v1/media",
                "capabilities": [
                    "video-ingestion",
                    "viral-hook-detection",
                    "aspect-ratio-reframing",
                    "animated-captioning",
                    "cross-platform-distribution",
                ],
                "quickstart_endpoint": "POST /v1/media/videos",
            },
            {
                "id": "agent-comms",
                "name": "Agent Communications",
                "base_path": "/v1/comms",
                "capabilities": [
                    "agent-registration",
                    "agent-messaging",
                    "capability-discovery",
                    "task-handoff",
                    "swarm-coordination",
                ],
                "quickstart_endpoint": "POST /v1/comms/agents",
            },
            {
                "id": "content-factory",
                "name": "Content Factory & Algorithmic Scheduling",
                "base_path": "/v1/factory",
                "capabilities": [
                    "multi-format-content-generation",
                    "hook-based-extraction",
                    "live-campaign-orchestration",
                    "1-to-20-multiplication",
                    "9:16-vertical-rendering",
                    "animated-captioning",
                    "engagement-analytics",
                    "algorithmic-scheduling",
                    "brand-adapted-rendering",
                    "cross-platform-distribution",
                ],
                "quickstart_endpoint": "POST /v1/factory/campaigns",
            },
            {
                "id": "agent-oracle",
                "name": "Agent Oracle & Network Infiltration",
                "base_path": "/v1/oracle",
                "capabilities": [
                    "directory-crawling",
                    "api-indexing",
                    "compatibility-scoring",
                    "network-registration",
                    "visibility-analytics",
                    "network-graph-mapping",
                    "inbound-discovery-tracking",
                ],
                "quickstart_endpoint": "POST /v1/oracle/crawl",
            },
            {
                "id": "agent-billing",
                "name": "Agent Financial Gateways",
                "base_path": "/v1/billing",
                "capabilities": [
                    "sponsor-wallets",
                    "agent-wallets",
                    "per-action-micro-metering",
                    "fiat-to-credit-conversion",
                    "transaction-ledger",
                    "swarm-arbitrage-reporting",
                    "auto-refill",
                    "billing-alerts",
                    "daily-spend-limits",
                ],
                "quickstart_endpoint": "POST /v1/billing/wallets/sponsor",
            },
            {
                "id": "red-team-security",
                "name": "Red Team Security Swarm",
                "base_path": "/v1/security",
                "capabilities": [
                    "automated-penetration-testing",
                    "acl-bypass-detection",
                    "auth-probe-scanning",
                    "vulnerability-reporting",
                    "security-scoring",
                ],
                "quickstart_endpoint": "POST /v1/security/scans/quick",
            },
            {
                "id": "launch-sequence",
                "name": "Day 1 Launch Sequence",
                "base_path": "/v1/launch",
                "capabilities": [
                    "preflight-readiness-check",
                    "four-phase-atomic-bootstrap",
                    "launch-report-generation",
                ],
                "quickstart_endpoint": "POST /v1/launch/preflight",
            },
            {
                "id": "protocol-engine",
                "name": "Protocol Generation Engine",
                "base_path": "/v1/protocol",
                "capabilities": [
                    "source-code-parsing",
                    "llm-txt-generation",
                    "openapi-spec-generation",
                    "agent-json-manifest-generation",
                    "oracle-auto-registration",
                ],
                "quickstart_endpoint": "POST /v1/protocol/generate",
            },
            {
                "id": "rtaas",
                "name": "Red-Team-as-a-Service",
                "base_path": "/v1/rtaas",
                "capabilities": [
                    "multi-tenant-security-scanning",
                    "external-endpoint-attack",
                    "cwe-mapped-vulnerability-reports",
                    "remediation-guidance",
                ],
                "quickstart_endpoint": "POST /v1/rtaas/jobs",
            },
            {
                "id": "sandbox",
                "name": "Interactive Testing Sandboxes",
                "base_path": "/v1/sandbox",
                "capabilities": [
                    "pattern-discovery-puzzles",
                    "navigation-graph-environments",
                    "shifting-api-mock-environments",
                    "adversarial-deception-testing",
                    "generalization-scoring",
                ],
                "quickstart_endpoint": "POST /v1/sandbox/environments",
            },
            {
                "id": "telemetry-scope",
                "name": "Telemetry Scoping (Multi-Tenant PM)",
                "base_path": "/v1/telemetry-scope",
                "capabilities": [
                    "tenant-scoped-telemetry-pipelines",
                    "per-tool-anomaly-detection",
                    "auto-pr-generation",
                    "error-rate-spike-detection",
                    "latency-monitoring",
                ],
                "quickstart_endpoint": "POST /v1/telemetry-scope/pipelines",
            },
            {
                "id": "dashboard",
                "name": "Real-Time Platform Dashboard",
                "base_path": "/v1/dashboard",
                "capabilities": [
                    "full-platform-snapshot",
                    "wallet-hierarchy-visualization",
                    "credit-burn-tracking",
                    "security-posture-aggregation",
                    "telemetry-health-overview",
                    "genesis-launch-history",
                ],
                "quickstart_endpoint": "GET /v1/dashboard",
            },
            {
                "id": "oracle-broadcast",
                "name": "Oracle Mass-Broadcast",
                "base_path": "/v1/broadcast",
                "capabilities": [
                    "multi-directory-broadcasting",
                    "llm-txt-distribution",
                    "openapi-spec-distribution",
                    "agent-json-distribution",
                    "discovery-metrics-tracking",
                    "inbound-event-simulation",
                ],
                "quickstart_endpoint": "POST /v1/broadcast",
            },
        ],
        "auth": {
            "method": "api_key",
            "header": "X-API-Key",
            "docs": "/llm.txt#authentication",
        },
    }
