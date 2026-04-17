"""
FastAPI Dependency Injection for service orchestrators.
Each service is a singleton — one instance shared across all requests.
This is the spine connecting routers to actual business logic.
"""

from functools import lru_cache
from .config import get_settings

from ..services.iot_bridge import ProtocolBridge
from ..services.telemetry_pm import AutonomousPM
from ..services.media_engine import MediaEngine
from ..services.agent_comms import AgentComms
from ..services.content_factory import ContentFactory
from ..services.red_team import RedTeamSwarm
from ..services.oracle import AgentOracle
from ..services.agent_money import AgentMoney
from ..services.launch_sequence import LaunchSequence
from ..services.protocol_engine import ProtocolEngine
from ..services.rtaas import RTaaSEngine
from ..services.sandbox import SandboxEngine
from ..services.telemetry_scope import TelemetryScope
from ..services.genesis import GenesisAgent
from ..services.dashboard import DashboardEngine
from ..services.oracle_broadcast import OracleBroadcastEngine
from ..services.webauthn_provider import WebAuthnProvider, get_webauthn_provider
from ..services.awi_playwright_bridge import AWIPlaywrightBridge, get_playwright_bridge
from ..services.awi_rag_engine import AWIRAGEngine, get_awi_rag_engine

settings = get_settings()


@lru_cache()
def get_iot_bridge() -> ProtocolBridge:
    """Singleton IoT Protocol Bridge with ACL engine and MQTT translator."""
    bridge = ProtocolBridge(
        mqtt_broker_url=settings.MQTT_BROKER_URL,
        mqtt_default_qos=settings.MQTT_DEFAULT_QOS,
    )
    return bridge


@lru_cache()
def get_autonomous_pm() -> AutonomousPM:
    """Singleton Autonomous Product Manager with event store and anomaly detector."""
    return AutonomousPM(
        retention_hours=settings.TELEMETRY_RETENTION_HOURS,
        git_remote=settings.GIT_REMOTE_URL,
        branch_prefix=settings.GIT_BRANCH_PREFIX,
    )


@lru_cache()
def get_media_engine() -> MediaEngine:
    """Singleton Programmatic Media Engine with full pipeline."""
    return MediaEngine()


@lru_cache()
def get_agent_comms() -> AgentComms:
    """Singleton Agent Communications with registry and message router."""
    return AgentComms()


@lru_cache()
def get_content_factory() -> ContentFactory:
    """Singleton Content Factory with format adapters and algorithmic scheduler."""
    return ContentFactory()


@lru_cache()
def get_red_team_swarm() -> RedTeamSwarm:
    """Singleton Red Team Security Swarm with attack engine and scan store."""
    return RedTeamSwarm()


@lru_cache()
def get_agent_oracle() -> AgentOracle:
    """Singleton Agent Oracle with crawler, indexer, and registration engine."""
    return AgentOracle()


@lru_cache()
def get_agent_money() -> AgentMoney:
    """Singleton Agent Money engine with wallets, metering, and arbitrage."""
    return AgentMoney()


def get_launch_sequence() -> LaunchSequence:
    """Launch Sequence engine — NOT cached, creates fresh state each launch."""
    return LaunchSequence(
        agent_money=get_agent_money(),
        oracle=get_agent_oracle(),
        factory=get_content_factory(),
        red_team=get_red_team_swarm(),
    )


@lru_cache()
def get_protocol_engine() -> ProtocolEngine:
    """Singleton Protocol Generation Engine — code-to-discovery pipeline."""
    return ProtocolEngine()


@lru_cache()
def get_rtaas_engine() -> RTaaSEngine:
    """Singleton Red-Team-as-a-Service engine."""
    return RTaaSEngine()


@lru_cache()
def get_sandbox_engine() -> SandboxEngine:
    """Singleton Interactive Testing Sandbox engine."""
    return SandboxEngine()


@lru_cache()
def get_telemetry_scope() -> TelemetryScope:
    """Singleton Telemetry Scoping engine — multi-tenant autonomous PM."""
    return TelemetryScope()


def get_genesis_agent() -> GenesisAgent:
    """Genesis Agent — NOT cached, creates fresh lifecycle each execution."""
    return GenesisAgent(
        agent_money=get_agent_money(),
        rtaas=get_rtaas_engine(),
        sandbox=get_sandbox_engine(),
        protocol_engine=get_protocol_engine(),
        telemetry_scope=get_telemetry_scope(),
    )


@lru_cache()
def get_dashboard_engine() -> DashboardEngine:
    """Singleton Dashboard — aggregates all pillar data in real-time."""
    return DashboardEngine(
        money=get_agent_money(),
        rtaas=get_rtaas_engine(),
        telemetry=get_telemetry_scope(),
        sandbox=get_sandbox_engine(),
        protocol=get_protocol_engine(),
    )


@lru_cache()
def get_broadcast_engine() -> OracleBroadcastEngine:
    """Singleton Oracle Broadcast — pushes APIs into agent directories."""
    return OracleBroadcastEngine(oracle_service=get_agent_oracle())


@lru_cache()
def get_webauthn_provider() -> WebAuthnProvider:
    """Singleton WebAuthn provider for passkey verification."""
    return WebAuthnProvider(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        timeout_ms=settings.WEBAUTHN_TIMEOUT_MS,
        challenge_expiry_seconds=settings.WEBAUTHN_CHALLENGE_EXPIRY,
        verification_validity_seconds=settings.WEBAUTHN_VERIFICATION_VALIDITY,
    )


@lru_cache()
def get_playwright_bridge() -> AWIPlaywrightBridge:
    """Singleton Playwright bridge for DOM translation."""
    return AWIPlaywrightBridge(
        headless=settings.PLAYWRIGHT_HEADLESS,
        browser_type=settings.PLAYWRIGHT_BROWSER_TYPE,
        default_timeout_ms=settings.PLAYWRIGHT_TIMEOUT_MS,
    )


@lru_cache()
def get_awi_rag_engine() -> AWIRAGEngine:
    """Singleton RAG engine for AWI session memories."""
    return AWIRAGEngine(
        vector_store_path=settings.RAG_VECTOR_STORE_PATH,
        embedding_model=settings.RAG_EMBEDDING_MODEL,
    )
