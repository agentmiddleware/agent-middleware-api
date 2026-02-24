"""
Real-Time Dashboard — Router
================================
The investor demo. One GET and you see the entire platform state.

Endpoints:
- GET  /v1/dashboard           — Full platform snapshot
- GET  /v1/dashboard/economics — Wallet hierarchy & credit metrics
- GET  /v1/dashboard/security  — RTaaS aggregate posture
- GET  /v1/dashboard/telemetry — Pipeline health overview
- GET  /v1/dashboard/genesis   — Genesis launch history
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from datetime import datetime
from dataclasses import asdict

from ..core.auth import verify_api_key
from ..core.dependencies import get_dashboard_engine
from ..services.dashboard import DashboardEngine

router = APIRouter(
    prefix="/v1/dashboard",
    tags=["Real-Time Dashboard"],
    dependencies=[Depends(verify_api_key)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EconomicsResponse(BaseModel):
    total_sponsors: int
    total_agent_wallets: int
    total_child_wallets: int
    total_credits_in_system: float
    total_credits_spent: float
    total_delegated_to_children: float
    credit_velocity: float = Field(
        ..., description="Ratio of spent/total credits. Higher = faster burn."
    )
    wallet_tree: list[dict] = Field(
        default_factory=list,
        description="Hierarchical wallet tree: Sponsor → Agent → Child",
    )


class SecurityResponse(BaseModel):
    total_jobs: int
    total_targets_scanned: int
    total_vulnerabilities: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    avg_security_score: float
    most_common_category: str
    recent_jobs: list[dict]


class TelemetryResponse(BaseModel):
    total_pipelines: int
    total_events: int
    total_anomalies: int
    total_auto_prs: int
    avg_error_rate: float
    avg_latency_ms: float
    pipelines: list[dict]


class GenesisHistoryResponse(BaseModel):
    total_launches: int
    alive: int
    failed: int
    reports: list[dict]


class DashboardResponse(BaseModel):
    snapshot_at: datetime
    platform_status: str
    pillars_active: int
    total_api_routes: int
    economics: dict
    wallet_tree: list[dict]
    security: dict
    telemetry: dict
    sandbox: dict
    protocol: dict
    genesis_launches: int
    genesis_alive: int
    genesis_failed: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=DashboardResponse,
    summary="Full Platform Snapshot",
    description=(
        "Returns the complete real-time state of all 15 pillars:\n"
        "economics, security posture, telemetry health, sandbox scores, "
        "protocol coverage, and Genesis launch history."
    ),
)
async def get_dashboard(
    engine: DashboardEngine = Depends(get_dashboard_engine),
):
    snap = await engine.snapshot()
    return DashboardResponse(
        snapshot_at=snap.snapshot_at,
        platform_status=snap.platform_status,
        pillars_active=snap.pillars_active,
        total_api_routes=snap.total_api_routes,
        economics=asdict(snap.economics),
        wallet_tree=snap.wallet_tree,
        security=asdict(snap.security),
        telemetry=asdict(snap.telemetry),
        sandbox=asdict(snap.sandbox),
        protocol=asdict(snap.protocol),
        genesis_launches=snap.genesis_launches,
        genesis_alive=snap.genesis_alive,
        genesis_failed=snap.genesis_failed,
    )


@router.get(
    "/economics",
    response_model=EconomicsResponse,
    summary="Wallet Economics & Hierarchy",
    description="Credit metrics + full wallet tree (Sponsor → Agent → Child).",
)
async def get_economics(
    engine: DashboardEngine = Depends(get_dashboard_engine),
):
    snap = await engine.snapshot()
    return EconomicsResponse(
        **asdict(snap.economics),
        wallet_tree=snap.wallet_tree,
    )


@router.get(
    "/security",
    response_model=SecurityResponse,
    summary="Security Posture",
    description="Aggregate vulnerability metrics across all RTaaS jobs.",
)
async def get_security(
    engine: DashboardEngine = Depends(get_dashboard_engine),
):
    return SecurityResponse(**asdict(await engine._build_security()))


@router.get(
    "/telemetry",
    response_model=TelemetryResponse,
    summary="Telemetry Health Overview",
    description="Pipeline health, error rates, latencies, anomaly counts.",
)
async def get_telemetry(
    engine: DashboardEngine = Depends(get_dashboard_engine),
):
    return TelemetryResponse(**asdict(await engine._build_telemetry()))


@router.get(
    "/genesis",
    response_model=GenesisHistoryResponse,
    summary="Genesis Launch History",
    description="All Genesis Builder Agent lifecycle reports.",
)
async def get_genesis_history(
    engine: DashboardEngine = Depends(get_dashboard_engine),
):
    return GenesisHistoryResponse(
        total_launches=len(engine._genesis_reports),
        alive=sum(1 for r in engine._genesis_reports if r.get("status") == "ALIVE"),
        failed=sum(1 for r in engine._genesis_reports if r.get("status") != "ALIVE"),
        reports=engine._genesis_reports,
    )
