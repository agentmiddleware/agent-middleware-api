"""
Agent-Native Middleware API
===========================
Operational control plane for autonomous agents.

Agent-facing capabilities center on identity, billing, discovery, policy,
and execution governance for machine-native software tenants. Demo and
integration surfaces such as AWI, content generation, IoT bridging, and
sandboxes exercise that control plane.

Zero GUI. Your customer is an autonomous agent.
"""

import asyncio
import logging
from pathlib import Path
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .core.config import get_settings
from .core.durable_state import (
    DurableStateConfigError,
    close_durable_state,
    get_durable_state,
)
from .core.health import gather_dependency_report
from .core.rate_limiter import RateLimitMiddleware
from .core.trust_mode import (
    is_production_like_environment,
    validate_trust_mode_guardrails,
    warn_if_trust_mode_permissive,
)
from .db.database import SchemaInitError, init_db, close_db
from .services.mcp_phase9_tools import sync_proof_surface_mcp_registration
from .services.signing_keys import validate_signing_key_configuration
from .routers.well_known import get_agent_first_metadata
from .routers import (
    auth,
    iot,
    telemetry,
    media,
    comms,
    agent_comms_durable,
    docs,
    factory,
    content_generation,
    red_team,
    oracle,
    audit,
    billing,
    permits,
    receipts,
    evidence,
    preflight,
    protocol,
    rtaas,
    sandbox,
    sandbox_behavioral,
    telemetry_scope,
    broadcast,
    ai,
    webhooks,
    mcp,
    kyc,
    api_keys,
    keys,
    me,
    awi,
    awi_enhanced,
    discover,
    well_known,
    static,
    planner,
    policies,
)

settings = get_settings()
_REPO_ROOT = Path(__file__).resolve().parent.parent

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
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
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
    validate_trust_mode_guardrails(settings)
    warn_if_trust_mode_permissive(settings)
    signing_key_state = validate_signing_key_configuration(settings)
    logger.info(
        "app_startup",
        phase="signing_key_validated",
        state=signing_key_state,
    )

    cleanup_task: asyncio.Task | None = None
    startup_time = time.monotonic()

    async def periodic_cleanup():
        """Background task to cleanup expired entries from services."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                # Frozen proof surfaces do not run background work when they are
                # not mounted. This keeps production-like trust deployments from
                # importing or mutating demo-only state behind a disabled flag.
                if settings.ENABLE_PROOF_SURFACES:
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

                    # Telemetry retention sweep (per
                    # TELEMETRY_RETENTION_HOURS). Ingests do a lazy eviction too;
                    # this handles idle proof-surface systems.
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

                # Repair permit budget reservations orphaned by a crash between
                # reserve and the receipt write (only touches idle permits).
                if settings.DATABASE_URL:
                    from .services.idempotency import get_idempotency_service
                    from .services.mcp_dispatch_attempts import (
                        get_mcp_dispatch_attempt_service,
                    )
                    from .services.mcp_dispatch_reconciliation import (
                        get_mcp_dispatch_reconciliation_service,
                    )
                    from .services.permits import get_permit_service

                    dispatch_result = (
                        await get_mcp_dispatch_reconciliation_service().reconcile(
                            idle_seconds=300
                        )
                    )
                    if dispatch_result.repaired:
                        logger.info(
                            "cleanup_completed",
                            dispatch_prepared_finalized=(
                                dispatch_result.prepared_finalized
                            ),
                            dispatch_marked_uncertain=(
                                dispatch_result.dispatched_uncertain
                            ),
                            dispatch_terminal_recovered=(
                                dispatch_result.terminal_recovered
                            ),
                            dispatch_idempotency_recovered=(
                                dispatch_result.idempotency_recovered
                            ),
                        )
                    if dispatch_result.failed_attempt_ids:
                        logger.warning(
                            "mcp_dispatch_reconciliation_failures",
                            failed_count=len(dispatch_result.failed_attempt_ids),
                        )

                    dispatch_metrics = (
                        await get_mcp_dispatch_attempt_service().summarize(
                            idle_seconds=300
                        )
                    )
                    uncertainty_count = dispatch_metrics.state_counts.get(
                        "delivery_uncertain", 0
                    )
                    if uncertainty_count or dispatch_metrics.reconciliation_backlog:
                        logger.warning(
                            "mcp_dispatch_operator_alert",
                            delivery_uncertain=uncertainty_count,
                            stale_active=dispatch_metrics.stale_active,
                            unfinalized_terminal=(
                                dispatch_metrics.unfinalized_terminal
                            ),
                            terminal_idempotency_incomplete=(
                                dispatch_metrics.terminal_idempotency_incomplete
                            ),
                            reconciliation_backlog=(
                                dispatch_metrics.reconciliation_backlog
                            ),
                        )

                    corrected = await get_permit_service().reconcile_budgets()
                    if corrected:
                        logger.info(
                            "cleanup_completed",
                            permit_budgets_reconciled=corrected,
                        )

                    (
                        repaired,
                        needs_review,
                    ) = await get_idempotency_service().reconcile_stuck_records(
                        idle_seconds=300
                    )
                    if repaired or needs_review:
                        logger.info(
                            "cleanup_completed",
                            idempotency_records_repaired=repaired,
                            idempotency_records_needing_review=needs_review,
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
        from .core.trust_mode import is_production_like_environment

        try:
            await init_db()
            logger.info(
                "app_startup",
                phase="database_initialized",
                startup_time_s=time.monotonic() - startup_time,
            )
        except Exception as e:
            # Production-like (and any SchemaInitError) fail closed: do not
            # boot against a DB that still needs Alembic.
            if isinstance(e, SchemaInitError) or is_production_like_environment(
                settings.ENVIRONMENT
            ):
                logger.error(
                    "app_startup",
                    phase="database_init_failed",
                    error=str(e),
                )
                raise
            logger.warning("app_startup", phase="database_init_failed", error=str(e))

        if settings.TRUST_MODE_ENABLED:
            from .services.signing_keys import get_signing_key_service

            try:
                signing_key = await get_signing_key_service().ensure_active_key()
                logger.info(
                    "app_startup",
                    phase="trust_signing_key_ready",
                    key_id=signing_key.key_id,
                    startup_time_s=time.monotonic() - startup_time,
                )
            except Exception as e:
                logger.error(
                    "app_startup",
                    phase="trust_signing_key_failed",
                    error=str(e),
                )
                raise

    # Fail closed at boot in production-like envs (DurableStateConfigError)
    # rather than waiting for the first request that touches durable state.
    startup_time = time.monotonic()
    try:
        state_report = await get_durable_state().health_report()
        logger.info(
            "app_startup",
            phase="durable_state_ready",
            backend=state_report.get("backend"),
            enabled=state_report.get("enabled"),
            startup_time_s=time.monotonic() - startup_time,
        )
    except DurableStateConfigError:
        logger.error("app_startup", phase="durable_state_failed")
        raise

    startup_time = time.monotonic()
    sync_proof_surface_mcp_registration()
    logger.info(
        "app_startup",
        phase="mcp_proof_surface_registration_synced",
        enable_proof_surfaces=bool(settings.ENABLE_PROOF_SURFACES),
        startup_time_s=time.monotonic() - startup_time,
    )

    # The design-partner adapter is configuration-only and fail-closed. When
    # enabled, startup must complete MCP initialize + tools/list and register
    # the exact executable tool before the app advertises readiness.
    startup_time = time.monotonic()
    from .services.upstream_mcp import register_configured_upstream_mcp

    upstream_service = await register_configured_upstream_mcp(settings=settings)
    logger.info(
        "app_startup",
        phase="mcp_upstream_registration_synced",
        enabled=bool(settings.MCP_UPSTREAM_ENABLED),
        public_tool_id=(
            upstream_service.get("service_id") if upstream_service else None
        ),
        upstream_origin=(
            upstream_service.get("upstream_origin") if upstream_service else None
        ),
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
        "## MCP Trust Plane\n\n"
        "Agent Middleware API is a **governed MCP trust plane** for autonomous "
        "agent tool calls — not a full agent middleware platform.\n\n"
        "Credible wedge: exactly-once gateway authorization, debit, and receipt "
        "finalization for metered MCP calls. Remote side effects require the "
        "upstream to honor the forwarded idempotency key. See `/WEDGE.md` and "
        "`/SECURITY_LIMITATIONS.md`.\n\n"
        "### Canonical Loop\n\n"
        "`discover -> authenticate -> authorize -> invoke -> meter -> "
        "receipt -> audit -> govern`\n\n"
        "### Product Surface\n\n"
        "- **Scoped signed permits** — tool, wallet, budget, expiry, nonce\n"
        "- **Governed MCP invoke** — permit check, policy, idempotency, charge\n"
        "- **Wallet metering** — ledger-backed credits with exact decimals\n"
        "- **Signed receipts + evidence** — verifiable attempt outcomes\n"
        "- **Wallet audit chain** — tamper-evident per-wallet events\n"
        "- **Discovery** — `.well-known/agent.json`, `/mcp/tools.json`, "
        "`/llm.txt`, `/v1/discover`\n\n"
        "### Proof Surfaces\n\n"
        "AWI, browser, content, oracle, sandbox, media, IoT, red-team, and "
        "telemetry demos are labeled scaffolding. They mount only when "
        "`ENABLE_PROOF_SURFACES=true` and do not define the product.\n\n"
        "### Authentication\n\n"
        "Protected endpoints require an API key via the `X-API-Key` header.\n\n"
        "### For Agents\n\n"
        "Start at `/.well-known/agent.json`, then `/llm.txt` and "
        "`/mcp/tools.json`. Prefer `PUBLIC_URL` over any localhost server entry."
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
            "description": "Public API (set PUBLIC_URL)",
        },
        *(
            []
            if is_production_like_environment(settings.ENVIRONMENT)
            else [{"url": "http://localhost:8000", "description": "Local Development"}]
        ),
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

CORE_TRUST_ROUTERS = (
    auth,
    audit,
    policies,
    billing,
    permits,
    receipts,
    evidence,
    preflight,
    webhooks,
    mcp,
    kyc,
    api_keys,
    keys,
    me,
    discover,
    planner,
    well_known,
    static,
    docs,
)

# Frozen scaffolding — do not expand. See docs/PROOF_SURFACES.md.
PROOF_SURFACE_ROUTERS = (
    iot,
    telemetry,
    media,
    comms,
    agent_comms_durable,
    factory,
    content_generation,
    red_team,
    oracle,
    protocol,
    rtaas,
    sandbox,
    sandbox_behavioral,
    telemetry_scope,
    broadcast,
    ai,
    awi,
    awi_enhanced,
)

for router_module in CORE_TRUST_ROUTERS:
    app.include_router(router_module.router)

if settings.ENABLE_PROOF_SURFACES:
    for router_module in PROOF_SURFACE_ROUTERS:
        app.include_router(router_module.router)
else:
    logger.info(
        "proof_surfaces_disabled: ENABLE_PROOF_SURFACES=false; "
        "only CORE_TRUST_ROUTERS are mounted"
    )


# --- Discovery & Health Endpoints ---


@app.get(
    "/",
    tags=["Discovery"],
    summary="API root — service index & human dashboard negotiation",
    description=(
        "Returns a broad service catalog for API callers or HTML dashboard for browsers. "
        "For agent-first bootstrap, follow `GET /.well-known/agent.json` → field `agent_first`."
    ),
    responses={
        200: {
            "description": "JSON service index or HTML control deck",
            "content": {"text/html": {"schema": {"type": "string"}}},
        }
    },
)
async def root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        dashboard_path = _REPO_ROOT / "static" / "dashboard.html"
        if dashboard_path.is_file():
            return HTMLResponse(
                dashboard_path.read_text(encoding="utf-8"),
                media_type="text/html; charset=utf-8",
            )

    payload: dict[str, Any] = {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "agent_first": get_agent_first_metadata(),
        "description": (
            "Operational control plane for autonomous agents: identity, billing, "
            "discovery, policy, and execution governance for machine-native "
            "software tenants."
        ),
        "surface_boundaries": {
            "core_trust": [
                "audit",
                "billing",
                "permits",
                "receipts",
                "evidence",
                "mcp",
                "api_keys",
                "signing_keys",
                "kyc",
                "discover",
                "planner",
                "policies",
            ],
            "proof_surface": [
                "awi",
                "browser_automation",
                "content_generation",
                "iot_bridge",
                "media_engine",
                "oracle",
                "red_team",
                "rtaas",
                "sandbox",
                "telemetry_pm",
            ],
            "proof_surfaces_mounted": bool(get_settings().ENABLE_PROOF_SURFACES),
        },
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
                    "POST /v1/agent-comms/send",
                    "GET /v1/agent-comms/inbox",
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
                    "POST /v1/content/generate",
                    "GET /v1/content/{content_id}",
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
                    "POST /v1/billing/top-up/prepare",
                    "GET /v1/billing/pricing",
                    "GET /v1/billing/arbitrage",
                    "GET /v1/billing/alerts",
                ],
            },
            "mcp_server": {
                "base_path": "/mcp",
                "description": (
                    "Model Context Protocol (MCP) gateway for governed tool "
                    "discovery and execution (permit → meter → dispatch → "
                    "receipt)."
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
            "capability_index": "/v1/discover",
            "dependency_truth": "/health/dependencies",
        },
    }
    if not get_settings().ENABLE_PROOF_SURFACES:
        # Only advertise mounted core trust services when proof surfaces are off.
        payload["services"] = {
            key: value
            for key, value in payload["services"].items()
            if key in {"agent_billing", "mcp_server"}
        }
    return payload


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
        "Stripe, LLM provider, signing key) in parallel with a short timeout. "
        "Each entry reports status, latency_ms, and an error message when unreachable. "
        "Deps whose consumers are in simulation mode return `not_used` so "
        "the health verdict doesn't degrade on mock-only deployments."
    ),
)
async def health_dependencies():
    return await gather_dependency_report()
