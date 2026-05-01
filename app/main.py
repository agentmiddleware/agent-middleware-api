"""
Agent-Native Middleware API
===========================
Headless infrastructure for the Business-to-Agent (B2A) economy.

Agent-facing capabilities include device protocol bridging, telemetry-driven
code repair, media and content pipelines, agent communications, discovery,
billing, security testing, sandboxes, MCP tooling, KYC, API key management,
and AWI integrations.

Zero GUI. Your customer is an autonomous agent.
"""

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.durable_state import close_durable_state, get_durable_state
from .core.health import gather_dependency_report
from .core.rate_limiter import RateLimitMiddleware
from .db.database import init_db, close_db
from .services.mcp_phase9_tools import (
    ensure_phase9_registered,
    register_default_mcp_services,
)
from .routers import (
    iot,
    telemetry,
    media,
    comms,
    docs,
    factory,
    red_team,
    oracle,
    billing,
    launch,
    protocol,
    rtaas,
    sandbox,
    sandbox_behavioral,
    telemetry_scope,
    dashboard,
    broadcast,
    ai,
    webhooks,
    mcp,
    kyc,
    api_keys,
    awi,
    awi_enhanced,
    discover,
    well_known,
    static,
)

settings = get_settings()

# Try structured logging, fall back to standard logging
try:
    import structlog

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()
    _USE_STRUCTLOG = True
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger(__name__)
    _USE_STRUCTLOG = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task: asyncio.Task | None = None
    startup_time = time.monotonic()

    async def periodic_cleanup():
        """Background task to cleanup expired entries from services."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                from .services.webauthn_provider import get_webauthn_provider

                webauthn = get_webauthn_provider()
                result = webauthn.cleanup_expired()
                if (
                    result["challenges_removed"] > 0
                    or result["verifications_removed"] > 0
                ):
                    logger.info(
                        "cleanup_completed",
                        challenges_removed=result["challenges_removed"],
                        verifications_removed=result["verifications_removed"],
                    )

                from .services.awi_session import get_awi_session_manager

                session_mgr = get_awi_session_manager()
                result = await session_mgr.cleanup_expired_async()
                if result["sessions_removed"] > 0:
                    logger.info(
                        "cleanup_completed",
                        sessions_removed=result["sessions_removed"],
                    )

                # Telemetry retention sweep (per TELEMETRY_RETENTION_HOURS).
                # Ingests do a lazy eviction too; this handles idle systems.
                if settings.DATABASE_URL:
                    from .services.telemetry_pm import EventStore

                    removed = await EventStore(
                        retention_hours=settings.TELEMETRY_RETENTION_HOURS
                    )._evict_expired()
                    if removed:
                        logger.info(
                            "cleanup_completed",
                            telemetry_events_removed=removed,
                        )

            except asyncio.CancelledError:
                logger.info("cleanup_task_stopped")
                break
            except Exception as e:
                logger.warning("cleanup_error", error=str(e))

    cleanup_task = asyncio.create_task(periodic_cleanup())
    logger.info(
        "app_startup",
        phase="cleanup_task_started",
        startup_time_s=time.monotonic() - startup_time,
    )

    startup_time = time.monotonic()
    if settings.DATABASE_URL:
        try:
            await init_db()
            logger.info(
                "app_startup",
                phase="database_initialized",
                startup_time_s=time.monotonic() - startup_time,
            )
        except Exception as e:
            logger.warning("app_startup", phase="database_init_failed", error=str(e))

    startup_time = time.monotonic()
    ensure_phase9_registered()
    logger.info(
        "app_startup",
        phase="phase9_tools_registered",
        startup_time_s=time.monotonic() - startup_time,
    )

    startup_time = time.monotonic()
    register_default_mcp_services()
    logger.info(
        "app_startup",
        phase="default_mcp_services_registered",
        startup_time_s=time.monotonic() - startup_time,
    )

    logger.info("app_ready", version=settings.APP_VERSION)

    yield

    logger.info("app_shutdown", phase="starting")
    shutdown_start = time.monotonic()

    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("app_shutdown", phase="cleanup_task_stopped")

    await close_db()
    await close_durable_state()

    await asyncio.sleep(2)  # Allow in-flight requests to drain
    logger.info(
        "app_shutdown",
        phase="complete",
        shutdown_duration_s=time.monotonic() - shutdown_start,
    )


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "## Agent-Native Middleware API\n\n"
        "Headless infrastructure for the B2A (Business-to-Agent) economy. "
        "This API provides a broad set of services that give AI agents the "
        "'hands' and 'eyes' to manipulate the digital and physical world.\n\n"
        "### Capability Surface\n\n"
        "- **IoT Protocol Bridge** (`/v1/iot`) — Secure, ACL-enforced protocol "
        "translation for IoT devices (MQTT, CoAP, Zigbee, etc.)\n"
        "- **Autonomous Product Manager** (`/v1/telemetry`) — Ingest telemetry, "
        "detect anomalies, auto-generate pull requests to fix bugs\n"
        "- **Programmatic Media Engine** (`/v1/media`) — Video ingestion, viral hook "
        "detection, reframing, captioning, and cross-platform distribution\n"
        "- **Agent Communications** (`/v1/comms`) — Agent registration, structured "
        "messaging, capability discovery, and swarm task handoffs\n"
        "- **Extended Agent Operations** — Content factory, oracle discovery, "
        "billing, MCP tools, security scanning, launch automation, protocol "
        "generation, RTaaS, sandboxes, telemetry scopes, dashboards, broadcast, "
        "AI helpers, webhooks, KYC, API keys, AWI, discovery, well-known, and "
        "static documentation routes\n\n"
        "### Authentication\n\n"
        "All endpoints require an API key passed via the `X-API-Key` header.\n\n"
        "### For Agents\n\n"
        "This API is designed for programmatic consumption. See `/llm.txt` for "
        "LLM-optimized documentation and `/openapi.json` for the full spec.\n\n"
        "### v0.2.0\n\n"
        "✅ Now MCP-native with discoverable monetized tools, dry-run sandboxing, "
        "KYC gating, and automatic key rotation."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "Agent-Native Middleware",
        "email": "support@agent-middleware.dev",
    },
    license_info={
        "name": "MIT",
    },
    servers=[
        {
            "url": settings.PUBLIC_URL or "https://api.yourdomain.com",
            "description": "Production",
        },
        {"url": "http://localhost:8000", "description": "Local Development"},
    ],
)

# --- Middleware Stack ---

# Rate limiting (enforces documented 120 req/min per API key)
app.add_middleware(RateLimitMiddleware)

# CORS — configurable via CORS_ORIGINS env var (comma-separated)
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Mount service routers ---
app.include_router(iot.router)
app.include_router(telemetry.router)
app.include_router(media.router)
app.include_router(comms.router)
app.include_router(factory.router)
app.include_router(red_team.router)
app.include_router(oracle.router)
app.include_router(billing.router)
app.include_router(launch.router)
app.include_router(protocol.router)
app.include_router(rtaas.router)
app.include_router(sandbox.router)
app.include_router(sandbox_behavioral.router)
app.include_router(telemetry_scope.router)
app.include_router(dashboard.router)
app.include_router(broadcast.router)
app.include_router(ai.router)
app.include_router(docs.router)
app.include_router(webhooks.router)
app.include_router(mcp.router)
app.include_router(kyc.router)
app.include_router(api_keys.router)
app.include_router(awi.router)
app.include_router(awi_enhanced.router)
app.include_router(discover.router)
app.include_router(well_known.router)
app.include_router(static.router)


# --- Discovery & Health Endpoints ---


@app.get(
    "/",
    tags=["Discovery"],
    summary="API root — agent discovery endpoint",
    description=(
        "Returns a machine-readable manifest of all available services, "
        "their base paths, and links to documentation. This is the first "
        "endpoint an agent should hit to understand what this API offers."
    ),
)
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": (
            "Agent-native middleware for IoT bridging, autonomous code repair, "
            "media distribution, agent communications, discovery, billing, "
            "security, sandboxes, MCP tooling, and AWI integrations."
        ),
        "services": {
            "iot_bridge": {
                "base_path": "/v1/iot",
                "description": (
                    "Secure protocol translation for IoT devices with topic-level ACLs."
                ),
                "endpoints": [
                    "POST /v1/iot/devices",
                    "GET /v1/iot/devices",
                    "GET /v1/iot/devices/{device_id}",
                    "DELETE /v1/iot/devices/{device_id}",
                    "POST /v1/iot/devices/{device_id}/messages",
                    "POST /v1/iot/devices/{device_id}/subscribe",
                ],
            },
            "autonomous_pm": {
                "base_path": "/v1/telemetry",
                "description": (
                    "Telemetry ingestion, anomaly detection, and autonomous "
                    "pull request generation."
                ),
                "endpoints": [
                    "POST /v1/telemetry/events",
                    "POST /v1/telemetry/events/single",
                    "GET /v1/telemetry/anomalies",
                    "GET /v1/telemetry/anomalies/{anomaly_id}",
                    "POST /v1/telemetry/anomalies/{anomaly_id}/auto-pr",
                    "GET /v1/telemetry/stats",
                ],
            },
            "media_engine": {
                "base_path": "/v1/media",
                "description": (
                    "Video-to-viral-clip pipeline with cross-platform distribution."
                ),
                "endpoints": [
                    "POST /v1/media/videos",
                    "GET /v1/media/videos/{video_id}",
                    "GET /v1/media/videos/{video_id}/hooks",
                    "POST /v1/media/videos/{video_id}/clips",
                    "POST /v1/media/distribute",
                    "GET /v1/media/clips/{clip_id}",
                ],
            },
            "agent_comms": {
                "base_path": "/v1/comms",
                "description": (
                    "Agent-to-agent messaging, capability discovery, and "
                    "swarm task handoffs."
                ),
                "endpoints": [
                    "POST /v1/comms/agents",
                    "GET /v1/comms/agents",
                    "POST /v1/comms/messages",
                    "GET /v1/comms/messages/{agent_id}/inbox",
                    "POST /v1/comms/messages/{agent_id}/ack/{message_id}",
                    "POST /v1/comms/handoff",
                ],
            },
            "content_factory": {
                "base_path": "/v1/factory",
                "description": (
                    "Multi-format content generation from single sources, "
                    "with hook-based 1-to-20 multiplication, 9:16 vertical "
                    "rendering, animated captions, and algorithmic posting "
                    "schedule optimization."
                ),
                "endpoints": [
                    "POST /v1/factory/pipelines",
                    "GET /v1/factory/pipelines/{pipeline_id}",
                    "GET /v1/factory/pipelines/{pipeline_id}/content",
                    "GET /v1/factory/content/{content_id}",
                    "POST /v1/factory/campaigns",
                    "GET /v1/factory/campaigns/{campaign_id}",
                    "GET /v1/factory/campaigns",
                    "POST /v1/factory/analytics",
                    "GET /v1/factory/analytics/summary",
                    "POST /v1/factory/schedule",
                ],
            },
            "agent_oracle": {
                "base_path": "/v1/oracle",
                "description": (
                    "Agent network infiltration: crawl directories, index APIs, "
                    "compute compatibility, register for inbound discovery "
                    "traffic."
                ),
                "endpoints": [
                    "POST /v1/oracle/crawl",
                    "POST /v1/oracle/crawl/batch",
                    "GET /v1/oracle/index",
                    "GET /v1/oracle/index/{api_id}",
                    "POST /v1/oracle/register",
                    "GET /v1/oracle/registrations",
                    "GET /v1/oracle/visibility",
                    "GET /v1/oracle/network",
                    "POST /v1/oracle/discovery",
                ],
            },
            "agent_billing": {
                "base_path": "/v1/billing",
                "description": (
                    "Two-tier wallet system with per-action micro-metering, "
                    "fiat-to-credit conversion, and swarm arbitrage profit "
                    "engine."
                ),
                "endpoints": [
                    "POST /v1/billing/wallets/sponsor",
                    "POST /v1/billing/wallets/agent",
                    "POST /v1/billing/wallets/child",
                    "POST /v1/billing/wallets/{wallet_id}/reclaim",
                    "GET /v1/billing/wallets/{wallet_id}/swarm",
                    "GET /v1/billing/wallets/{wallet_id}",
                    "GET /v1/billing/wallets",
                    "GET /v1/billing/ledger/{wallet_id}",
                    "POST /v1/billing/charge",
                    "POST /v1/billing/top-up",
                    "GET /v1/billing/pricing",
                    "GET /v1/billing/arbitrage",
                    "GET /v1/billing/alerts",
                ],
            },
            "mcp_server": {
                "base_path": "/mcp",
                "description": (
                    "Model Context Protocol (MCP) server for B2A tool "
                    "discovery and execution."
                ),
                "endpoints": [
                    "GET /mcp/tools.json",
                    "GET /.well-known/mcp/tools.json",
                    "POST /mcp/messages",
                    "GET /mcp/tools",
                    "GET /mcp/tools/{service_id}",
                    "POST /mcp/tools/{service_id}/invoke",
                ],
            },
            "red_team_security": {
                "base_path": "/v1/security",
                "description": (
                    "Autonomous penetration testing swarm. Continuously attacks "
                    "all API endpoints to find vulnerabilities before "
                    "external agents do."
                ),
                "endpoints": [
                    "POST /v1/security/scans",
                    "GET /v1/security/scans",
                    "GET /v1/security/scans/{scan_id}",
                    "GET /v1/security/scans/{scan_id}/vulnerabilities",
                    "POST /v1/security/scans/quick",
                ],
            },
            "launch_sequence": {
                "base_path": "/v1/launch",
                "description": (
                    "Day 1 production bootstrap. One POST funds wallets, "
                    "infiltrates agent networks, ignites content campaigns, "
                    "and arms the Red Team perimeter."
                ),
                "endpoints": [
                    "POST /v1/launch/preflight",
                    "POST /v1/launch",
                    "POST /v1/launch/genesis",
                    "GET /v1/launch/reports",
                ],
            },
            "protocol_engine": {
                "base_path": "/v1/protocol",
                "description": (
                    "Code-to-discovery pipeline. Feed raw API code, get "
                    "llm.txt + OpenAPI spec + agent.json + Oracle registration."
                ),
                "endpoints": [
                    "POST /v1/protocol/generate",
                    "GET /v1/protocol/generations",
                    "GET /v1/protocol/generations/{generation_id}",
                ],
            },
            "rtaas": {
                "base_path": "/v1/rtaas",
                "description": (
                    "Red-Team-as-a-Service. Hire our security swarm to "
                    "attack YOUR endpoints before deployment."
                ),
                "endpoints": [
                    "POST /v1/rtaas/jobs",
                    "GET /v1/rtaas/jobs",
                    "GET /v1/rtaas/jobs/{job_id}",
                    "GET /v1/rtaas/jobs/{job_id}/vulnerabilities",
                ],
            },
            "sandbox": {
                "base_path": "/v1/sandbox",
                "description": (
                    "Interactive testing sandboxes. Headless puzzle "
                    "environments for testing agent generalization."
                ),
                "endpoints": [
                    "POST /v1/sandbox/environments",
                    "POST /v1/sandbox/environments/{env_id}/actions",
                    "POST /v1/sandbox/environments/{env_id}/evaluate",
                    "GET /v1/sandbox/environments/{env_id}",
                    "GET /v1/sandbox/environments",
                ],
            },
            "awi_phase9": {
                "base_path": "/v1/awi",
                "description": (
                    "AWI Phase 9 enhanced capabilities: FIDO2 passkey auth, "
                    "bidirectional DOM bridge, and RAG-based semantic memory."
                ),
                "endpoints": [
                    "POST /v1/awi/passkey/register",
                    "POST /v1/awi/passkey/challenge",
                    "POST /v1/awi/passkey/verify",
                    "GET /v1/awi/passkey/list/{wallet_id}",
                    "DELETE /v1/awi/passkey/{credential_id}",
                    "POST /v1/awi/dom/snapshot",
                    "POST /v1/awi/dom/element_at",
                    "POST /v1/awi/dom/execute",
                    "POST /v1/awi/dom/query",
                    "POST /v1/awi/dom/to_awi",
                    "POST /v1/awi/rag/ingest",
                    "POST /v1/awi/rag/search",
                    "POST /v1/awi/rag/context",
                    "GET /v1/awi/rag/list/{wallet_id}",
                    "DELETE /v1/awi/rag/{memory_id}",
                    "DELETE /v1/awi/rag/clear/{wallet_id}",
                ],
            },
            "telemetry_scope": {
                "base_path": "/v1/telemetry-scope",
                "description": (
                    "Multi-tenant autonomous PM. Scoped telemetry "
                    "pipelines with anomaly detection and auto-PR generation."
                ),
                "endpoints": [
                    "POST /v1/telemetry-scope/pipelines",
                    "POST /v1/telemetry-scope/pipelines/{pipeline_id}/events",
                    "GET /v1/telemetry-scope/pipelines/{pipeline_id}/anomalies",
                    "POST /v1/telemetry-scope/pipelines/{pipeline_id}/auto-pr",
                    "GET /v1/telemetry-scope/pipelines/{pipeline_id}/stats",
                    "GET /v1/telemetry-scope/pipelines/{pipeline_id}",
                    "GET /v1/telemetry-scope/pipelines",
                ],
            },
            "dashboard": {
                "base_path": "/v1/dashboard",
                "description": (
                    "Real-time platform monitoring. Full snapshot of "
                    "economics, security, telemetry, and Genesis lifecycle."
                ),
                "endpoints": [
                    "GET /v1/dashboard",
                    "GET /v1/dashboard/economics",
                    "GET /v1/dashboard/security",
                    "GET /v1/dashboard/telemetry",
                    "GET /v1/dashboard/genesis",
                ],
            },
            "oracle_broadcast": {
                "base_path": "/v1/broadcast",
                "description": (
                    "Push published APIs into agent directories. "
                    "The network effects engine."
                ),
                "endpoints": [
                    "POST /v1/broadcast",
                    "GET /v1/broadcast/jobs",
                    "GET /v1/broadcast/jobs/{job_id}",
                    "GET /v1/broadcast/jobs/{job_id}/metrics",
                    "POST /v1/broadcast/jobs/{job_id}/events",
                    "GET /v1/broadcast/directories",
                ],
            },
        },
        "auth": {
            "method": "api_key",
            "header": "X-API-Key",
            "description": (
                "Pass your API key in the X-API-Key header on every request."
            ),
        },
        "rate_limits": {
            "requests_per_minute": settings.RATE_LIMIT_PER_MINUTE,
            "headers": [
                "X-RateLimit-Limit",
                "X-RateLimit-Remaining",
                "X-RateLimit-Reset",
            ],
        },
        "docs": {
            "openapi": "/openapi.json",
            "interactive": "/docs",
            "redoc": "/redoc",
            "llm_txt": "/llm.txt",
            "agent_manifest": "/.well-known/agent.json",
        },
    }


@app.get(
    "/health",
    tags=["Discovery"],
    summary="Liveness check",
    description="Returns 200 if the API is running. Use for Kubernetes livenessProbe.",
)
async def health():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
    }


@app.get(
    "/health/ready",
    tags=["Discovery"],
    summary="Readiness check",
    description="Returns 200 if all dependencies are ready. Use for Kubernetes readinessProbe.",
)
async def health_ready():
    checks: dict[str, dict[str, Any]] = {}
    all_healthy = True

    state_report = await get_durable_state().health_report()
    checks["state_store"] = {
        "status": "up" if state_report.get("ok", False) else "down",
        "backend": state_report.get("backend", "unknown"),
    }
    if checks["state_store"]["status"] == "down":
        all_healthy = False

    checks["mqtt"] = {
        "status": "up" if settings.MQTT_BROKER_URL else "not_configured",
        "configured": bool(settings.MQTT_BROKER_URL),
    }

    if settings.DATABASE_URL:
        checks["database"] = {"status": "up", "configured": True}
    else:
        checks["database"] = {"status": "not_configured", "configured": False}

    return {
        "status": "ready" if all_healthy else "not_ready",
        "version": settings.APP_VERSION,
        "checks": checks,
    }


@app.get(
    "/health/dependencies",
    tags=["Discovery"],
    summary="Dependency health check",
    description=(
        "Probes every external dependency (PostgreSQL, Redis, MQTT broker, "
        "Stripe, LLM provider) in parallel with a short timeout. Each entry "
        "reports status, latency_ms, and an error message when unreachable. "
        "Deps whose consumers are in simulation mode return `not_used` so "
        "the health verdict doesn't degrade on mock-only deployments."
    ),
)
async def health_dependencies():
    return await gather_dependency_report()
