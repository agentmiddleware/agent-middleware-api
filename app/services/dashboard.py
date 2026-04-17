"""
Real-Time Genesis Dashboard — Service
======================================
Aggregates telemetry from all 15 pillars into a single real-time
monitoring payload. The investor demo in an API call.

Data sources:
- Agent Money: wallet hierarchy, credit burn, swarm delegation
- RTaaS: security posture, vulnerability trends
- Telemetry Scope: error rates, latency, anomalies
- Sandbox: generalization scores, environment stats
- Protocol Engine: published APIs, discovery coverage
- Genesis: lifecycle reports, phase timings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from ..services.agent_money import AgentMoney
from ..services.rtaas import RTaaSEngine
from ..services.telemetry_scope import TelemetryScope
from ..services.sandbox import SandboxEngine
from ..services.protocol_engine import ProtocolEngine
from ..schemas.billing import WalletType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class WalletNode:
    """Single node in the wallet hierarchy tree."""
    wallet_id: str
    wallet_type: str
    owner: str
    balance: float
    lifetime_credits: float
    lifetime_debits: float
    max_spend: float | None = None
    spent: float = 0.0
    status: str = "active"
    children: list[WalletNode] = field(default_factory=list)


@dataclass
class SecurityPosture:
    """Aggregate security metrics across all RTaaS jobs."""
    total_jobs: int = 0
    total_targets_scanned: int = 0
    total_vulnerabilities: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    avg_security_score: float = 0.0
    most_common_category: str = "none"
    recent_jobs: list[dict] = field(default_factory=list)


@dataclass
class TelemetryOverview:
    """Aggregate telemetry across all pipelines."""
    total_pipelines: int = 0
    total_events: int = 0
    total_anomalies: int = 0
    total_auto_prs: int = 0
    avg_error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    pipelines: list[dict] = field(default_factory=list)


@dataclass
class SandboxOverview:
    """Aggregate sandbox metrics."""
    total_environments: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    avg_generalization_score: float = 0.0
    solved_count: int = 0
    total_actions: int = 0


@dataclass
class ProtocolOverview:
    """Aggregate protocol generation metrics."""
    total_generations: int = 0
    total_endpoints_documented: int = 0
    formats_generated: list[str] = field(default_factory=list)


@dataclass
class EconomicMetrics:
    """The money story — burn rate, arbitrage, delegation."""
    total_sponsors: int = 0
    total_agent_wallets: int = 0
    total_child_wallets: int = 0
    total_credits_in_system: float = 0.0
    total_credits_spent: float = 0.0
    total_delegated_to_children: float = 0.0
    credit_velocity: float = 0.0  # spent / total ratio


@dataclass
class DashboardSnapshot:
    """Complete real-time dashboard state."""
    snapshot_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    platform_status: str = "OPERATIONAL"
    pillars_active: int = 15
    total_api_routes: int = 92

    # Economics
    economics: EconomicMetrics = field(default_factory=EconomicMetrics)
    wallet_tree: list[dict] = field(default_factory=list)

    # Security
    security: SecurityPosture = field(default_factory=SecurityPosture)

    # Telemetry
    telemetry: TelemetryOverview = field(default_factory=TelemetryOverview)

    # Sandbox
    sandbox: SandboxOverview = field(default_factory=SandboxOverview)

    # Protocol
    protocol: ProtocolOverview = field(default_factory=ProtocolOverview)

    # Genesis history
    genesis_launches: int = 0
    genesis_alive: int = 0
    genesis_failed: int = 0


# ---------------------------------------------------------------------------
# Dashboard Engine
# ---------------------------------------------------------------------------

class DashboardEngine:
    """Aggregates all pillar data into a single real-time snapshot."""

    def __init__(
        self,
        money: AgentMoney,
        rtaas: RTaaSEngine,
        telemetry: TelemetryScope,
        sandbox: SandboxEngine,
        protocol: ProtocolEngine,
    ):
        self.money = money
        self.rtaas = rtaas
        self.telemetry = telemetry
        self.sandbox = sandbox
        self.protocol = protocol

        # Genesis report store (populated by launch router)
        self._genesis_reports: list[dict] = []

    def record_genesis(self, report: dict) -> None:
        """Record a Genesis launch report for dashboard tracking."""
        self._genesis_reports.append(report)

    async def snapshot(self) -> DashboardSnapshot:
        """Build a complete dashboard snapshot by querying all subsystems."""
        snap = DashboardSnapshot()

        # --- Economics ---
        snap.economics = await self._build_economics()
        snap.wallet_tree = await self._build_wallet_tree()

        # --- Security ---
        snap.security = await self._build_security()

        # --- Telemetry ---
        snap.telemetry = await self._build_telemetry()

        # --- Sandbox ---
        snap.sandbox = await self._build_sandbox()

        # --- Protocol ---
        snap.protocol = await self._build_protocol()

        # --- Genesis ---
        snap.genesis_launches = len(self._genesis_reports)
        snap.genesis_alive = sum(
            1 for r in self._genesis_reports if r.get("status") == "ALIVE"
        )
        snap.genesis_failed = snap.genesis_launches - snap.genesis_alive

        return snap

    # -----------------------------------------------------------------------
    # Subsystem aggregators
    # -----------------------------------------------------------------------

    async def _build_economics(self) -> EconomicMetrics:
        """Aggregate wallet economics."""
        metrics = EconomicMetrics()

        all_wallets = await self.money.list_wallets()
        for w in all_wallets:
            if w.wallet_type == WalletType.SPONSOR:
                metrics.total_sponsors += 1
            elif w.wallet_type == WalletType.AGENT:
                metrics.total_agent_wallets += 1
            elif w.wallet_type == WalletType.CHILD:
                metrics.total_child_wallets += 1
                metrics.total_delegated_to_children += w.lifetime_credits

            metrics.total_credits_in_system += w.balance
            metrics.total_credits_spent += w.lifetime_debits

        if metrics.total_credits_in_system + metrics.total_credits_spent > 0:
            metrics.credit_velocity = round(
                metrics.total_credits_spent
                / (metrics.total_credits_in_system + metrics.total_credits_spent),
                4,
            )

        return metrics

    async def _build_wallet_tree(self) -> list[dict]:
        """Build hierarchical wallet tree for visualization."""
        all_wallets = await self.money.list_wallets()
        nodes: dict[str, WalletNode] = {}

        # Create nodes
        for w in all_wallets:
            nodes[w.wallet_id] = WalletNode(
                wallet_id=w.wallet_id,
                wallet_type=(
                    w.wallet_type.value
                    if hasattr(w.wallet_type, "value")
                    else str(w.wallet_type)
                ),
                owner=w.owner_name,
                balance=round(w.balance, 2),
                lifetime_credits=round(w.lifetime_credits, 2),
                lifetime_debits=round(w.lifetime_debits, 2),
                max_spend=w.max_spend,
                spent=round(w.lifetime_debits, 2),
                status=w.status.value if hasattr(w.status, 'value') else str(w.status),
            )

        # Build tree (sponsor → agent → child)
        roots: list[WalletNode] = []
        for w in all_wallets:
            node = nodes[w.wallet_id]
            parent_id = (
                getattr(w, "sponsor_wallet_id", None)
                or getattr(w, "parent_wallet_id", None)
            )
            if parent_id and parent_id in nodes:
                nodes[parent_id].children.append(node)
            else:
                roots.append(node)

        return [asdict(r) for r in roots]

    async def _build_security(self) -> SecurityPosture:
        """Aggregate RTaaS security posture."""
        posture = SecurityPosture()
        jobs = await self.rtaas.list_jobs()

        posture.total_jobs = len(jobs)
        category_counts: dict[str, int] = {}

        for job in jobs:
            posture.total_targets_scanned += len(job.targets)
            for vuln in job.vulnerabilities:
                posture.total_vulnerabilities += 1
                sev = vuln.severity
                if sev == "critical":
                    posture.critical_count += 1
                elif sev == "high":
                    posture.high_count += 1
                elif sev == "medium":
                    posture.medium_count += 1
                else:
                    posture.low_count += 1

                cat = (
                    vuln.category.value
                    if hasattr(vuln.category, "value")
                    else str(vuln.category)
                )
                category_counts[cat] = category_counts.get(cat, 0) + 1

            posture.recent_jobs.append({
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "targets": len(job.targets),
                "vulns": len(job.vulnerabilities),
                "score": job.security_score,
                "status": job.status,
                "created_at": str(job.created_at),
            })

        if jobs:
            scores = [j.security_score for j in jobs if j.security_score is not None]
            posture.avg_security_score = (
                round(sum(scores) / len(scores), 1) if scores else 0.0
            )

        if category_counts:
            posture.most_common_category = max(
                category_counts, key=lambda k: category_counts.get(k, 0)
            )

        # Only keep latest 10 jobs
        posture.recent_jobs = posture.recent_jobs[:10]

        return posture

    async def _build_telemetry(self) -> TelemetryOverview:
        """Aggregate telemetry across all pipelines."""
        overview = TelemetryOverview()
        pipelines = await self.telemetry.list_pipelines()

        overview.total_pipelines = len(pipelines)
        error_rates: list[float] = []
        latencies: list[float] = []

        for pipe in pipelines:
            stats = await self.telemetry.get_pipeline_stats(pipe.pipeline_id)
            overview.total_events += stats["total_events"]
            overview.total_anomalies += stats["anomalies_detected"]
            overview.total_auto_prs += stats["auto_prs_generated"]

            if stats["total_events"] > 0:
                error_rates.append(stats["error_rate"])
                if stats["avg_latency_ms"] > 0:
                    latencies.append(stats["avg_latency_ms"])

            overview.pipelines.append({
                "pipeline_id": pipe.pipeline_id,
                "tenant_id": pipe.tenant_id,
                "service": pipe.service_name,
                "events": stats["total_events"],
                "anomalies": stats["anomalies_detected"],
                "error_rate": round(stats["error_rate"], 4),
                "status": pipe.status,
            })

        if error_rates:
            overview.avg_error_rate = round(sum(error_rates) / len(error_rates), 4)
        if latencies:
            overview.avg_latency_ms = round(sum(latencies) / len(latencies), 1)

        return overview

    async def _build_sandbox(self) -> SandboxOverview:
        """Aggregate sandbox metrics."""
        overview = SandboxOverview()
        envs = await self.sandbox.list_environments()

        overview.total_environments = len(envs)
        scores: list[float] = []

        for env in envs:
            env_type = (
                env.env_type.value
                if hasattr(env.env_type, "value")
                else str(env.env_type)
            )
            overview.by_type[env_type] = overview.by_type.get(env_type, 0) + 1
            overview.total_actions += env.state.step

            if env.generalization_score is not None:
                scores.append(env.generalization_score)
                if env.state.solved:
                    overview.solved_count += 1

        if scores:
            overview.avg_generalization_score = round(sum(scores) / len(scores), 1)

        return overview

    async def _build_protocol(self) -> ProtocolOverview:
        """Aggregate protocol generation metrics."""
        overview = ProtocolOverview()
        gens = await self.protocol.list_generations()

        overview.total_generations = len(gens)
        formats_seen: set[str] = set()

        for gen in gens:
            overview.total_endpoints_documented += gen.endpoints_parsed
            # Every generation produces all 3 formats
            formats_seen.update(["llm_txt", "openapi", "agent_json"])

        overview.formats_generated = sorted(formats_seen)

        return overview
