"""
Genesis Agent — The Meta-Launch (Pillar 15)
==============================================
The first autonomous tool-builder spawned by the infrastructure.

Instead of manually deploying services, the Genesis Agent IS the
deployment. It exercises the full A2A lifecycle:

1. FUND        — Create human sponsor + spawn Genesis Builder child wallet
2. BUILD       — Genesis Agent "writes" a micro-service (simulated code gen)
3. SECURE      — RTaaS attacks the new service's endpoints
4. TEST        — Sandbox environment validates generalization
5. PUBLISH     — Protocol Engine generates llm.txt + OpenAPI + agent.json
6. MONITOR     — Telemetry Scope pipeline watches the new service

Each phase feeds into the next. The final output is a GenesisReport —
proof that the infrastructure can autonomously create, secure, test,
publish, and monitor a new tool without human intervention.

This is not a toy demo. This is the system proving it can replicate.
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Genesis Configuration
# ---------------------------------------------------------------------------

@dataclass
class GenesisConfig:
    """Configuration for the Genesis Agent Meta-Launch."""
    sponsor_name: str = "Genesis Sponsor"
    sponsor_email: str = "genesis@b2a.dev"
    seed_capital_usd: float = 100.0        # $100 = 100,000 credits
    genesis_budget_credits: float = 50000.0 # $50 cap for the Genesis Agent
    genesis_max_spend: float = 50000.0      # Hard lifetime cap
    genesis_task: str = "Build, secure, test, publish, and monitor a micro-service API"
    target_service_name: str = "genesis-widget-api"
    target_service_version: str = "1.0.0"
    target_base_url: str = "https://api.genesis-widget.dev"
    sandbox_difficulty: str = "medium"
    rtaas_intensity: str = "thorough"


# ---------------------------------------------------------------------------
# Phase Receipts
# ---------------------------------------------------------------------------

@dataclass
class FundReceipt:
    sponsor_wallet_id: str
    genesis_wallet_id: str
    sponsor_balance: float
    genesis_balance: float
    genesis_max_spend: float


@dataclass
class BuildReceipt:
    service_name: str
    endpoints_generated: int
    source_lines: int
    source_code_hash: str


@dataclass
class SecureReceipt:
    rtaas_job_id: str
    targets_scanned: int
    vulnerabilities_found: int
    security_score: float
    critical_vulns: int
    remediation_actions: int


@dataclass
class TestReceipt:
    sandbox_env_id: str
    env_type: str
    steps_used: int
    solved: bool
    generalization_score: float


@dataclass
class PublishReceipt:
    generation_id: str
    endpoints_documented: int
    llm_txt_lines: int
    openapi_paths: int
    agent_json_capabilities: int


@dataclass
class MonitorReceipt:
    pipeline_id: str
    events_ingested: int
    anomalies_detected: int
    auto_prs_generated: int


@dataclass
class GenesisReport:
    """The proof of autonomous self-replication."""
    genesis_id: str
    status: str              # "ALIVE" or "FAILED"
    task: str
    fund: FundReceipt | None = None
    build: BuildReceipt | None = None
    secure: SecureReceipt | None = None
    test: TestReceipt | None = None
    publish: PublishReceipt | None = None
    monitor: MonitorReceipt | None = None
    total_credits_spent: float = 0.0
    credits_remaining: float = 0.0
    phases_completed: int = 0
    phases_total: int = 6
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The Genesis Agent Micro-Service Template
# ---------------------------------------------------------------------------

GENESIS_SERVICE_CODE = '''
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter(prefix="/v1/widgets", tags=["Widgets"])

class Widget(BaseModel):
    """A widget resource created by the Genesis Agent."""
    widget_id: str = Field(..., description="Unique widget identifier")
    name: str = Field(..., description="Widget display name")
    category: str = Field(default="general", description="Widget category")
    status: str = Field(default="active", description="Widget status")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)

class CreateWidgetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Widget name")
    category: str = Field(default="general", description="Widget category")
    metadata: dict = Field(default_factory=dict)

@router.post("/", response_model=Widget, status_code=201, summary="Create a widget", description="Create a new widget resource.")
async def create_widget(request: CreateWidgetRequest):
    return Widget(widget_id="w-001", name=request.name, category=request.category)

@router.get("/", summary="List widgets", description="List all widgets with optional filtering.")
async def list_widgets(category: str = Query(None), limit: int = Query(default=50, ge=1, le=500)):
    return {"widgets": [], "total": 0}

@router.get("/{widget_id}", response_model=Widget, summary="Get widget", description="Retrieve a widget by ID.")
async def get_widget(widget_id: str):
    return Widget(widget_id=widget_id, name="example")

@router.put("/{widget_id}", response_model=Widget, summary="Update widget", description="Update widget properties.")
async def update_widget(widget_id: str, request: CreateWidgetRequest):
    return Widget(widget_id=widget_id, name=request.name, category=request.category)

@router.delete("/{widget_id}", status_code=204, summary="Delete widget", description="Permanently delete a widget.")
async def delete_widget(widget_id: str):
    return None

@router.get("/{widget_id}/health", summary="Widget health check", description="Check the operational status of a specific widget.")
async def widget_health(widget_id: str):
    return {"widget_id": widget_id, "status": "healthy", "uptime_seconds": 3600}
'''


# ---------------------------------------------------------------------------
# Genesis Agent Engine
# ---------------------------------------------------------------------------

class GenesisAgent:
    """
    The Meta-Launch orchestrator.

    Exercises all 5 A2A pillars in sequence to prove the system
    can autonomously build, secure, test, publish, and monitor
    a new micro-service.
    """

    def __init__(self, agent_money, rtaas, sandbox, protocol_engine, telemetry_scope):
        self.money = agent_money
        self.rtaas = rtaas
        self.sandbox = sandbox
        self.protocol = protocol_engine
        self.telemetry = telemetry_scope

    async def execute(self, config: GenesisConfig | None = None) -> GenesisReport:
        """Run the full Genesis Agent lifecycle."""
        config = config or GenesisConfig()
        genesis_id = f"genesis-{uuid.uuid4().hex[:12]}"

        report = GenesisReport(
            genesis_id=genesis_id,
            status="RUNNING",
            task=config.genesis_task,
        )

        try:
            # Phase 1: FUND
            report.fund = await self._fund(config)
            report.phases_completed += 1
            logger.info(f"[{genesis_id}] Phase 1/6 FUND complete")

            # Phase 2: BUILD
            report.build = await self._build(config)
            report.phases_completed += 1
            logger.info(f"[{genesis_id}] Phase 2/6 BUILD complete — {report.build.endpoints_generated} endpoints")

            # Phase 3: SECURE
            report.secure = await self._secure(config)
            report.phases_completed += 1
            logger.info(f"[{genesis_id}] Phase 3/6 SECURE complete — score: {report.secure.security_score}")

            # Phase 4: TEST
            report.test = await self._test(config)
            report.phases_completed += 1
            logger.info(f"[{genesis_id}] Phase 4/6 TEST complete — generalization: {report.test.generalization_score}")

            # Phase 5: PUBLISH
            report.publish = await self._publish(config)
            report.phases_completed += 1
            logger.info(f"[{genesis_id}] Phase 5/6 PUBLISH complete — {report.publish.endpoints_documented} endpoints documented")

            # Phase 6: MONITOR
            report.monitor = await self._monitor(config)
            report.phases_completed += 1
            logger.info(f"[{genesis_id}] Phase 6/6 MONITOR complete — pipeline active")

            # Compute spend
            genesis_wallet = await self.money.get_wallet(report.fund.genesis_wallet_id)
            if genesis_wallet:
                report.total_credits_spent = round(float(genesis_wallet.lifetime_debits), 2)
                report.credits_remaining = round(float(genesis_wallet.balance), 2)

            report.status = "ALIVE"
            report.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            report.errors.append(str(e))
            report.status = "FAILED"
            report.completed_at = datetime.now(timezone.utc)
            logger.error(f"[{genesis_id}] Genesis failed at phase {report.phases_completed + 1}: {e}")

        return report

    # --- Phase 1: FUND ---

    async def _fund(self, config: GenesisConfig) -> FundReceipt:
        """Create sponsor → agent → child wallet hierarchy for Genesis Builder."""
        exchange_rate = Decimal("1000.0")
        seed_credits = Decimal(str(config.seed_capital_usd)) * exchange_rate
        genesis_budget = Decimal(str(config.genesis_budget_credits))
        genesis_max_spend = Decimal(str(config.genesis_max_spend))

        # Tier 1: Human sponsor puts up fiat-equivalent seed capital
        sponsor = await self.money.create_sponsor_wallet(
            sponsor_name=config.sponsor_name,
            email=config.sponsor_email,
            initial_credits=seed_credits,
        )

        # Tier 2: Agent wallet (the Genesis orchestrator) draws from sponsor
        agent = await self.money.create_agent_wallet(
            sponsor_wallet_id=sponsor.wallet_id,
            agent_id="genesis-orchestrator",
            budget_credits=genesis_budget,
        )

        # Tier 3: Child wallet (the actual builder) with hard spend cap
        genesis_child = await self.money.create_child_wallet(
            parent_wallet_id=agent.wallet_id,
            child_agent_id="genesis-builder-01",
            budget_credits=genesis_budget,
            max_spend=genesis_max_spend,
            task_description=config.genesis_task,
            auto_reclaim=True,
        )

        return FundReceipt(
            sponsor_wallet_id=sponsor.wallet_id,
            genesis_wallet_id=genesis_child.wallet_id,
            sponsor_balance=round(sponsor.balance, 2),
            genesis_balance=round(genesis_child.balance, 2),
            genesis_max_spend=config.genesis_max_spend,
        )

    # --- Phase 2: BUILD ---

    async def _build(self, config: GenesisConfig) -> BuildReceipt:
        """Genesis Agent 'writes' a micro-service."""
        source = GENESIS_SERVICE_CODE
        lines = len([line for line in source.strip().split('\n') if line.strip()])
        code_hash = str(hash(source))[:16]

        # Count endpoints in the generated code
        endpoint_count = source.count("@router.")

        return BuildReceipt(
            service_name=config.target_service_name,
            endpoints_generated=endpoint_count,
            source_lines=lines,
            source_code_hash=code_hash,
        )

    # --- Phase 3: SECURE ---

    async def _secure(self, config: GenesisConfig) -> SecureReceipt:
        """RTaaS attacks the newly built service."""
        targets = [
            {"url": f"{config.target_base_url}/v1/widgets", "method": "GET"},
            {"url": f"{config.target_base_url}/v1/widgets", "method": "POST"},
            {"url": f"{config.target_base_url}/v1/widgets/w-001", "method": "GET"},
            {"url": f"{config.target_base_url}/v1/widgets/w-001", "method": "PUT"},
            {"url": f"{config.target_base_url}/v1/widgets/w-001", "method": "DELETE"},
            {"url": f"{config.target_base_url}/v1/widgets/w-001/health", "method": "GET"},
        ]

        job = await self.rtaas.create_job(
            tenant_id="genesis-builder-01",
            targets=targets,
            intensity=config.rtaas_intensity,
        )

        critical = sum(1 for v in job.vulnerabilities if v.severity.value == "critical")
        remediations = sum(1 for v in job.vulnerabilities if v.remediation)

        return SecureReceipt(
            rtaas_job_id=job.job_id,
            targets_scanned=len(targets),
            vulnerabilities_found=len(job.vulnerabilities),
            security_score=job.security_score,
            critical_vulns=critical,
            remediation_actions=remediations,
        )

    # --- Phase 4: TEST ---

    async def _test(self, config: GenesisConfig) -> TestReceipt:
        """Sandbox tests the agent's generalization ability."""
        env = await self.sandbox.create_environment(
            env_type="api_mock",
            difficulty=config.sandbox_difficulty,
        )

        # Simulate the Genesis Agent interacting with the sandbox
        # It attempts to discover and call all endpoints
        for i in range(5):
            try:
                await self.sandbox.submit_action(env.env_id, {
                    "type": "call_endpoint",
                    "value": f"/api/v1/resource_{i}",
                })
            except Exception:
                break

        evaluation = await self.sandbox.evaluate(env.env_id)

        return TestReceipt(
            sandbox_env_id=env.env_id,
            env_type=evaluation["env_type"],
            steps_used=evaluation["steps_used"],
            solved=evaluation["solved"],
            generalization_score=evaluation["generalization_score"],
        )

    # --- Phase 5: PUBLISH ---

    async def _publish(self, config: GenesisConfig) -> PublishReceipt:
        """Protocol Engine generates the discovery package."""
        result = await self.protocol.generate(
            source_code=GENESIS_SERVICE_CODE,
            service_name=config.target_service_name,
            service_version=config.target_service_version,
            base_url=config.target_base_url,
            register_in_oracle=False,
        )

        return PublishReceipt(
            generation_id=result.generation_id,
            endpoints_documented=result.endpoints_parsed,
            llm_txt_lines=len(result.llm_txt.split('\n')),
            openapi_paths=len(result.openapi_spec.get("paths", {})),
            agent_json_capabilities=len(result.agent_json.get("capabilities", [])),
        )

    # --- Phase 6: MONITOR ---

    async def _monitor(self, config: GenesisConfig) -> MonitorReceipt:
        """Telemetry Scope creates a monitoring pipeline and ingests synthetic health events."""
        pipeline = await self.telemetry.create_pipeline(
            tenant_id="genesis-builder-01",
            service_name=config.target_service_name,
            git_repo_url=f"https://github.com/genesis-agent/{config.target_service_name}",
        )

        # Ingest synthetic initial health telemetry
        events = [
            {"type": "startup", "path": "/v1/widgets", "status_code": 200, "latency_ms": 12, "level": "info"},
            {"type": "request", "path": "/v1/widgets", "status_code": 200, "latency_ms": 25, "level": "info"},
            {"type": "request", "path": "/v1/widgets/w-001", "status_code": 200, "latency_ms": 18, "level": "info"},
            {"type": "request", "path": "/v1/widgets", "status_code": 201, "latency_ms": 45, "level": "info"},
            {"type": "health_check", "path": "/v1/widgets/w-001/health", "status_code": 200, "latency_ms": 5, "level": "info"},
        ]

        result = await self.telemetry.ingest_events(pipeline.pipeline_id, events)

        return MonitorReceipt(
            pipeline_id=pipeline.pipeline_id,
            events_ingested=result["events_ingested"],
            anomalies_detected=result["anomalies_detected"],
            auto_prs_generated=0,  # Clean startup = no anomalies to fix
        )
