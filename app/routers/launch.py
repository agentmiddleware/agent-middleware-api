"""
Day 1 Launch Sequence — Router
================================
The big red button. One POST and the autonomous startup goes live.

Endpoints:
- POST /v1/launch         — Execute full Day 1 launch sequence
- POST /v1/launch/fund    — Fund wallets only
- POST /v1/launch/status  — Get launch report
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime

from ..core.auth import verify_api_key
from ..core.dependencies import get_launch_sequence, get_genesis_agent
from ..services.launch_sequence import LaunchSequence, LaunchConfig
from ..services.preflight import PreflightEngine
from ..services.genesis import GenesisAgent, GenesisConfig

router = APIRouter(
    prefix="/v1/launch",
    tags=["Launch Sequence"],
    dependencies=[Depends(verify_api_key)],
)

# In-memory launch report store (production: PostgreSQL)
_launch_reports: list[dict] = []


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class LaunchRequest(BaseModel):
    """Day 1 launch configuration. All fields have battle-tested defaults."""
    sponsor_name: str = Field(
        default="B2A Seed Fund",
        description="Human sponsor name for the liability-sink root account.",
    )
    sponsor_email: str = Field(
        default="founder@yourdomain.com",
        description="Contact email for billing alerts.",
    )
    seed_capital_usd: float = Field(
        default=50.0,
        gt=0,
        description="Seed capital in USD. At $0.001/credit, $50 = 50,000 credits.",
    )
    agent_ids: list[str] = Field(
        default=["content-swarm-alpha", "oracle-crawler-01", "red-team-sentinel"],
        description="Agent IDs to provision with funded wallets.",
    )
    agent_budget_credits: float = Field(
        default=10000.0,
        gt=0,
        description="Credits per agent wallet.",
    )
    platforms: list[str] = Field(
        default=["youtube_shorts", "tiktok", "instagram_reels"],
        description="Content distribution platforms.",
    )
    max_posts_per_day: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max posts per platform per day (audience fatigue cap).",
    )


class PreflightRequest(BaseModel):
    """Optional overrides for preflight validation."""
    base_url: str = Field(
        default="",
        description="Production BASE_URL to validate (e.g., https://api.mycompany.com).",
    )
    stripe_secret_key: str = Field(
        default="",
        description="Stripe secret key to validate (sk_live_... for production).",
    )


class PreflightCheckResult(BaseModel):
    """Single preflight check outcome."""
    name: str
    passed: bool
    severity: str = Field(..., description="critical, warning, or info")
    message: str
    detail: str = ""


class PreflightResponse(BaseModel):
    """Pre-flight readiness report — the checklist before you turn the key."""
    checked_at: datetime
    verdict: str = Field(..., description="GO or NO-GO")
    total_checks: int
    passed: int
    failed: int
    warnings: int
    critical_failures: int
    checks: list[PreflightCheckResult]
    summary: str


class LaunchResponse(BaseModel):
    """Birth certificate of the autonomous system."""
    status: str = Field(..., description="LIVE or FAILED")
    launched_at: datetime
    sponsor_wallet_id: str
    agent_wallet_ids: list[str]
    total_credits_seeded: float
    apis_crawled: int
    directories_registered: int
    visibility_score: float
    campaign_id: str
    total_content_pieces: int
    scheduled_posts: int
    estimated_total_views: int
    security_score: float
    attack_vectors_tested: int
    summary: dict = Field(
        default_factory=dict,
        description="Complete launch metrics.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=LaunchResponse,
    status_code=201,
    summary="Execute Day 1 Launch Sequence",
    description=(
        "The ignition key. Executes all four launch phases in sequence:\n\n"
        "1. **FUND** — Create sponsor wallet, inject seed capital, provision agent wallets\n"
        "2. **INFILTRATE** — Crawl 6 major APIs, register in 4 agent directories\n"
        "3. **IGNITE** — Launch B2A content campaign (3 hooks × N formats = 40+ pieces)\n"
        "4. **ARM** — Activate Red Team perimeter scanning across all API paths\n\n"
        "Returns a LaunchResponse (the system's birth certificate) with full metrics."
    ),
)
async def execute_launch(
    request: LaunchRequest,
    launcher: LaunchSequence = Depends(get_launch_sequence),
):
    config = LaunchConfig(
        sponsor_name=request.sponsor_name,
        sponsor_email=request.sponsor_email,
        seed_capital_usd=request.seed_capital_usd,
        agent_ids=request.agent_ids,
        agent_budget_credits=request.agent_budget_credits,
        platforms=request.platforms,
        max_posts_per_day=request.max_posts_per_day,
    )

    try:
        report = await launcher.execute(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Launch failed: {str(e)}")

    response = LaunchResponse(
        status=report.status,
        launched_at=report.launched_at,
        sponsor_wallet_id=report.fund.sponsor_wallet_id,
        agent_wallet_ids=report.fund.agent_wallet_ids,
        total_credits_seeded=report.fund.total_credits_seeded,
        apis_crawled=report.infiltrate.apis_crawled,
        directories_registered=report.infiltrate.directories_registered,
        visibility_score=report.infiltrate.visibility_score,
        campaign_id=report.ignite.campaign_id,
        total_content_pieces=report.ignite.total_content_pieces,
        scheduled_posts=report.ignite.scheduled_posts,
        estimated_total_views=report.ignite.estimated_total_views,
        security_score=report.arm.security_score,
        attack_vectors_tested=report.arm.attack_vectors_tested,
        summary={
            "fund": {
                "sponsor_wallet": report.fund.sponsor_wallet_id,
                "agent_wallets": report.fund.agent_wallet_ids,
                "seed_capital_usd": report.fund.top_up_amount_usd,
                "credits_seeded": report.fund.total_credits_seeded,
            },
            "infiltrate": {
                "apis_indexed": report.infiltrate.apis_indexed,
                "native_tier": report.infiltrate.native_tier_count,
                "compatible_tier": report.infiltrate.compatible_tier_count,
                "visibility": report.infiltrate.visibility_score,
            },
            "ignite": {
                "campaign": report.ignite.campaign_id,
                "hooks": report.ignite.hooks_processed,
                "content_pieces": report.ignite.total_content_pieces,
                "scheduled": report.ignite.scheduled_posts,
                "est_views": report.ignite.estimated_total_views,
                "platforms": report.ignite.platforms,
            },
            "arm": {
                "scans": report.arm.scan_ids,
                "vulnerabilities": report.arm.total_vulnerabilities,
                "security_score": report.arm.security_score,
                "vectors_tested": report.arm.attack_vectors_tested,
            },
        },
    )

    # Store for retrieval
    _launch_reports.append(response.model_dump(mode="json"))

    return response


@router.post(
    "/preflight",
    response_model=PreflightResponse,
    summary="Pre-flight Readiness Check",
    description=(
        "Runs a comprehensive validation sweep before Day 1 launch:\n\n"
        "1. **KEYS** — Reject test-key/placeholder API keys, validate Stripe tokens\n"
        "2. **DOMAIN** — Verify BASE_URL is a real domain, manifests will resolve\n"
        "3. **ORACLE** — Validate agent directory registration URLs\n"
        "4. **ASSETS** — Check content source URLs and crawl targets\n\n"
        "Returns a GO/NO-GO verdict with per-check details. "
        "Fix all critical failures before calling POST /v1/launch."
    ),
)
async def run_preflight(request: PreflightRequest = PreflightRequest()):
    engine = PreflightEngine()

    config_overrides = {}
    if request.base_url:
        config_overrides["base_url"] = request.base_url
    if request.stripe_secret_key:
        config_overrides["stripe_secret_key"] = request.stripe_secret_key

    report = await engine.run(config_overrides)

    return PreflightResponse(
        checked_at=report.checked_at,
        verdict=report.verdict,
        total_checks=report.total_checks,
        passed=report.passed,
        failed=report.failed,
        warnings=report.warnings,
        critical_failures=report.critical_failures,
        checks=[
            PreflightCheckResult(**c) for c in report.checks
        ],
        summary=report.summary,
    )


class GenesisRequest(BaseModel):
    """Configuration for the Genesis Agent Meta-Launch."""
    sponsor_name: str = Field(default="Genesis Sponsor", description="Human sponsor name.")
    sponsor_email: str = Field(default="genesis@b2a.dev", description="Sponsor email.")
    seed_capital_usd: float = Field(default=100.0, description="Seed capital in USD.")
    genesis_budget_credits: float = Field(default=50000.0, description="Genesis Agent budget (credits).")
    genesis_max_spend: float = Field(default=50000.0, description="Hard lifetime spend cap (credits).")
    target_service_name: str = Field(default="genesis-widget-api", description="Name of the micro-service the Genesis Agent will build.")


class GenesisPhaseDetail(BaseModel):
    """Detail for a single Genesis phase."""
    phase: str
    data: dict


class GenesisResponse(BaseModel):
    """The proof of autonomous self-replication."""
    genesis_id: str
    status: str = Field(..., description="ALIVE or FAILED")
    task: str
    phases_completed: int
    phases_total: int
    total_credits_spent: float
    credits_remaining: float
    fund: dict | None = None
    build: dict | None = None
    secure: dict | None = None
    test: dict | None = None
    publish: dict | None = None
    monitor: dict | None = None
    errors: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None


@router.post(
    "/genesis",
    response_model=GenesisResponse,
    status_code=201,
    summary="Meta-Launch: Spawn the Genesis Builder Agent",
    description=(
        "The ultimate proof of infrastructure autonomy. Executes a 6-phase lifecycle:\n\n"
        "1. **FUND** — Create sponsor wallet, spawn Genesis Builder child wallet with spend cap\n"
        "2. **BUILD** — Genesis Agent writes a micro-service API\n"
        "3. **SECURE** — RTaaS attacks the new service (thorough intensity)\n"
        "4. **TEST** — Sandbox validates the agent's generalization ability\n"
        "5. **PUBLISH** — Protocol Engine generates llm.txt + OpenAPI + agent.json\n"
        "6. **MONITOR** — Telemetry Scope pipeline watches the new service\n\n"
        "Returns a GenesisReport — proof that the infrastructure can self-replicate."
    ),
)
async def execute_genesis(
    request: GenesisRequest = GenesisRequest(),
    genesis: GenesisAgent = Depends(get_genesis_agent),
):
    config = GenesisConfig(
        sponsor_name=request.sponsor_name,
        sponsor_email=request.sponsor_email,
        seed_capital_usd=request.seed_capital_usd,
        genesis_budget_credits=request.genesis_budget_credits,
        genesis_max_spend=request.genesis_max_spend,
        target_service_name=request.target_service_name,
    )

    report = await genesis.execute(config)

    from dataclasses import asdict
    def to_dict(obj):
        return asdict(obj) if obj else None

    return GenesisResponse(
        genesis_id=report.genesis_id,
        status=report.status,
        task=report.task,
        phases_completed=report.phases_completed,
        phases_total=report.phases_total,
        total_credits_spent=report.total_credits_spent,
        credits_remaining=report.credits_remaining,
        fund=to_dict(report.fund),
        build=to_dict(report.build),
        secure=to_dict(report.secure),
        test=to_dict(report.test),
        publish=to_dict(report.publish),
        monitor=to_dict(report.monitor),
        errors=report.errors,
        started_at=report.started_at,
        completed_at=report.completed_at,
    )


@router.get(
    "/reports",
    summary="Get all launch reports",
    description="Returns historical launch reports (birth certificates).",
)
async def list_launch_reports():
    return {
        "reports": _launch_reports,
        "total": len(_launch_reports),
    }
