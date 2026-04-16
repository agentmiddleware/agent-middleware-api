"""
LLM-Optimized Documentation Router
------------------------------------
Serves documentation in formats designed for agent consumption.
This is the new SEO: if an LLM can't parse your docs, agents won't
recommend your product.

Endpoints:
- /llm.txt — Flat-text summary for LLM context windows
- /docs/index — Structured JSON doc index for agent navigation
- /.well-known/agent.json — Standard agent discovery manifest
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
import os

router = APIRouter(
    tags=["Documentation & Discovery"],
)


@router.get(
    "/llm.txt",
    response_class=PlainTextResponse,
    summary="LLM-optimized documentation",
    description=(
        "Returns the full API documentation in a flat plaintext format "
        "designed for LLM context windows. This is the primary entry point "
        "for AI agents evaluating whether to recommend this API. "
        "Think of this as SEO for the agentic web."
    ),
)
async def get_llm_txt():
    # Serve from docs/llm.txt
    llm_txt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "docs", "llm.txt"
    )
    try:
        with open(llm_txt_path, "r") as f:
            content = f.read()
        return PlainTextResponse(content, media_type="text/plain")
    except FileNotFoundError:
        return PlainTextResponse(
            "# llm.txt not found. Run the documentation generator.",
            status_code=404,
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
        "version": "0.1.0",
        "format": "agent-native-docs/v1",
        "last_updated": "2026-02-22",
        "sections": [
            {
                "id": "overview",
                "title": "API Overview",
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


@router.get(
    "/.well-known/agent.json",
    summary="Agent discovery manifest",
    description=(
        "Standard agent discovery manifest following the emerging "
        ".well-known/agent.json convention. External agents fetch this to understand "
        "what this API does, how to authenticate, and what capabilities "
        "are available — similar to robots.txt but for AI agents."
    ),
)
async def get_agent_manifest():
    return {
        "schema_version": "1.0",
        "name": "Agent-Native Middleware API",
        "description": (
            "Headless middleware for the B2A economy. "
            "Provides IoT protocol bridging, autonomous code repair via telemetry, "
            "programmatic video-to-viral distribution, agent-to-agent communications, "
            "and multi-format content generation with algorithmic scheduling."
        ),
        "url": "https://api.yourdomain.com",
        "documentation_url": "https://api.yourdomain.com/llm.txt",
        "openapi_url": "https://api.yourdomain.com/openapi.json",
        "authentication": {
            "type": "api_key",
            "header": "X-API-Key",
            "registration": "https://api.yourdomain.com/v1/comms/agents",
        },
        "capabilities": [
            {
                "name": "iot-protocol-bridging",
                "description": (
                    "Securely bridge IoT protocols (MQTT, CoAP, Zigbee, etc.) "
                    "to REST with topic-level ACLs."
                ),
                "endpoint": "/v1/iot",
            },
            {
                "name": "autonomous-code-repair",
                "description": (
                    "Ingest telemetry, detect anomalies, and auto-generate pull "
                    "requests to fix bugs."
                ),
                "endpoint": "/v1/telemetry",
            },
            {
                "name": "programmatic-media-distribution",
                "description": (
                    "Video-to-viral-clip pipeline with cross-platform "
                    "distribution."
                ),
                "endpoint": "/v1/media",
            },
            {
                "name": "agent-to-agent-messaging",
                "description": (
                    "Structured messaging, capability discovery, and "
                    "task handoffs between agents."
                ),
                "endpoint": "/v1/comms",
            },
            {
                "name": "content-factory-scheduling",
                "description": (
                    "Hook-based 1-to-20 content multiplication with 9:16 vertical "
                    "rendering, animated captions, live campaign orchestration, "
                    "and engagement-optimized algorithmic scheduling."
                ),
                "endpoint": "/v1/factory",
            },
            {
                "name": "agent-oracle-infiltration",
                "description": (
                    "Crawl agent directories, index external APIs, compute "
                    "compatibility scores, and register for inbound discovery "
                    "traffic across the agentic web."
                ),
                "endpoint": "/v1/oracle",
            },
            {
                "name": "agent-financial-gateways",
                "description": (
                    "Two-tier wallet system: human sponsors provision agent "
                    "wallets, per-action micro-metering, fiat-to-credit conversion, "
                    "and swarm arbitrage profit engine."
                ),
                "endpoint": "/v1/billing",
            },
            {
                "name": "red-team-security-swarm",
                "description": (
                    "Autonomous penetration testing that continuously attacks all API "
                    "endpoints to find vulnerabilities."
                ),
                "endpoint": "/v1/security",
            },
        ],
        "rate_limits": {
            "requests_per_minute": 120,
            "batch_counts_as_one": True,
        },
        "contact": {
            "email": "api@yourdomain.com",
        },
        "protocols": ["rest", "json", "openapi"],
    }
