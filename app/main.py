"""
Agent-Native Middleware API
============================
Headless infrastructure for the Business-to-Agent (B2A) economy.

Four service pillars:
1. IoT Protocol Bridge — Secure protocol translation for physical devices
2. Autonomous Product Manager — Telemetry-driven self-healing code
3. Programmatic Media Engine — Video-to-viral-clip pipeline
4. Agent Communications — Machine-to-machine messaging and swarm coordination

Zero GUI. Your customer is an autonomous agent.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .core.config import get_settings
from .core.durable_state import close_durable_state, get_durable_state
from .core.rate_limiter import RateLimitMiddleware
from .db.database import init_db, close_db
from .routers import (
    iot, telemetry, media, comms, docs, factory, red_team, oracle,
    billing, launch, protocol, rtaas, sandbox, telemetry_scope,
    dashboard, broadcast, ai, webhooks, mcp, kyc, api_keys,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database if configured
    if settings.DATABASE_URL:
        try:
            await init_db()
            logger.info("Database initialized")
        except Exception as e:
            logger.warning(f"Database initialization failed: {e}")

    yield

    # Shutdown: Close database connections
    await close_db()
    await close_durable_state()
    logger.info("Database connections closed")


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "## Agent-Native Middleware API\n\n"
        "Headless infrastructure for the B2A (Business-to-Agent) economy. "
        "This API provides four core services that give AI agents the "
        "'hands' and 'eyes' to manipulate the digital and physical world.\n\n"
        "### Service Pillars\n\n"
        "- **IoT Protocol Bridge** (`/v1/iot`) — Secure, ACL-enforced protocol "
        "translation for IoT devices (MQTT, CoAP, Zigbee, etc.)\n"
        "- **Autonomous Product Manager** (`/v1/telemetry`) — Ingest telemetry, "
        "detect anomalies, auto-generate pull requests to fix bugs\n"
        "- **Programmatic Media Engine** (`/v1/media`) — Video ingestion, viral hook "
        "detection, reframing, captioning, and cross-platform distribution\n"
        "- **Agent Communications** (`/v1/comms`) — Agent registration, structured "
        "messaging, capability discovery, and swarm task handoffs\n\n"
        "### Authentication\n\n"
        "All endpoints require an API key passed via the `X-API-Key` header.\n\n"
        "### For Agents\n\n"
        "This API is designed for programmatic consumption. See `/llm.txt` for "
        "LLM-optimized documentation and `/openapi.json` for the full spec."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "Agent-Native Middleware",
        "email": "api@yourdomain.com",
    },
    license_info={
        "name": "MIT",
    },
    servers=[
        {"url": "https://api.yourdomain.com", "description": "Production"},
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
app.include_router(telemetry_scope.router)
app.include_router(dashboard.router)
app.include_router(broadcast.router)
app.include_router(ai.router)
app.include_router(docs.router)
app.include_router(webhooks.router)
app.include_router(mcp.router)
app.include_router(kyc.router)
app.include_router(api_keys.router)


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
            "programmatic media distribution, and agent-to-agent communications."
        ),
        "services": {
            "iot_bridge": {
                "base_path": "/v1/iot",
                "description": (
                    "Secure protocol translation for IoT devices "
                    "with topic-level ACLs."
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
                    "Video-to-viral-clip pipeline with cross-platform "
                    "distribution."
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
                "Pass your API key in the X-API-Key header "
                "on every request."
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
    summary="Health check",
    description=(
        "Returns 200 if the API is running. Agents should poll "
        "this before routing traffic."
    ),
)
async def health():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
    }


@app.get(
    "/health/dependencies",
    tags=["Discovery"],
    summary="Dependency health check",
    description=(
        "Returns runtime dependency status for durable state backends "
        "(PostgreSQL/Redis) and MQTT configuration."
    ),
)
async def health_dependencies():
    state_report = await get_durable_state().health_report()
    return {
        "status": "healthy" if state_report.get("ok", False) else "degraded",
        "state_store": state_report,
        "mqtt": {
            "configured": bool(settings.MQTT_BROKER_URL),
            "broker_url": settings.MQTT_BROKER_URL,
        },
    }
