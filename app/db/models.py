"""
SQLModel database models for Agent Middleware API.
Defines normalized tables for wallets, ledger entries, and billing alerts.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field

from app.core.time import utc_now


class WalletModel(SQLModel, table=True):
    """
    Wallet table for storing agent and sponsor wallets.

    Uses Decimal for all monetary fields to avoid floating-point errors.
    """

    __tablename__ = "wallets"

    wallet_id: str = Field(primary_key=True, max_length=50)
    wallet_type: str = Field(max_length=20, index=True)
    owner_name: Optional[str] = Field(default=None, max_length=255)
    owner_key: Optional[str] = Field(default=None, max_length=255, index=True)
    email: Optional[str] = Field(default=None, max_length=255)

    # Monetary fields - all Decimal for precision
    balance: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=8)
    lifetime_credits: Decimal = Field(default=Decimal("0"), decimal_places=8)
    lifetime_debits: Decimal = Field(default=Decimal("0"), decimal_places=8)

    # Hierarchy fields (for agent/child wallets)
    parent_wallet_id: Optional[str] = Field(
        default=None, foreign_key="wallets.wallet_id", index=True
    )
    agent_id: Optional[str] = Field(default=None, max_length=100, index=True)

    # Child wallet specific fields
    child_agent_id: Optional[str] = Field(default=None, max_length=100)
    max_spend: Optional[Decimal] = Field(default=None, decimal_places=8)
    task_description: Optional[str] = Field(default=None, max_length=500)
    ttl_seconds: Optional[int] = Field(default=None)

    # Spending controls
    daily_limit: Optional[Decimal] = Field(default=None, decimal_places=8)
    daily_spent: Decimal = Field(default=Decimal("0"), decimal_places=8)
    daily_reset_at: Optional[datetime] = Field(default=None)

    # Velocity monitoring (spend per hour for anomaly detection)
    hourly_limit: Optional[Decimal] = Field(default=None, decimal_places=8)
    hourly_spent: Decimal = Field(default=Decimal("0"), decimal_places=8)
    hourly_reset_at: Optional[datetime] = Field(default=None)

    # Velocity anomaly detection
    last_charge_at: Optional[datetime] = Field(default=None)
    velocity_alerts_triggered: int = Field(default=0)

    # Auto-refill settings
    auto_refill: bool = Field(default=False)
    auto_refill_threshold: Decimal = Field(default=Decimal("100"), decimal_places=8)
    auto_refill_amount: Decimal = Field(default=Decimal("1000"), decimal_places=8)

    # Status and metadata
    status: str = Field(default="active", max_length=20)
    kyc_status: str = Field(default="not_required", max_length=30)
    kyc_verified_at: Optional[datetime] = Field(default=None)
    metadata_json: Optional[str] = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"arbitrary_types_allowed": True}


class LedgerEntryModel(SQLModel, table=True):
    """
    Ledger entry table for immutable transaction history.

    All amounts are Decimal. Positive = credit, negative = debit.
    """

    __tablename__ = "ledger_entries"

    entry_id: str = Field(primary_key=True, max_length=50)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)

    # Transaction details
    action: str = Field(max_length=20)
    amount: Decimal = Field(decimal_places=8)  # Positive = credit, negative = debit
    balance_after: Decimal = Field(ge=0, decimal_places=8)

    # Service categorization
    service_category: Optional[str] = Field(default=None, max_length=50, index=True)

    # Description and context
    description: str = Field(default="", max_length=500)
    request_path: Optional[str] = Field(default=None, max_length=255)

    # Cost accounting for arbitrage
    compute_cost: Optional[Decimal] = Field(default=None, decimal_places=8)
    margin: Optional[Decimal] = Field(default=None, decimal_places=8)

    # Metadata
    metadata_json: Optional[str] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None, max_length=100, index=True)

    # Stripe payment fields (for fiat top-up idempotency)
    payment_intent_id: Optional[str] = Field(
        default=None,
        max_length=100,
        index=True,
        unique=True,  # Enforces idempotency at DB level
    )
    stripe_session_id: Optional[str] = Field(default=None, max_length=100, index=True)

    # Timestamp
    timestamp: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class BillingAlertModel(SQLModel, table=True):
    """
    Billing alert table for tracking wallet warnings and notifications.
    """

    __tablename__ = "billing_alerts"

    alert_id: str = Field(primary_key=True, max_length=50)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)
    alert_type: str = Field(max_length=30, index=True)
    threshold_amount: Optional[Decimal] = Field(default=None, decimal_places=8)
    current_balance: Optional[Decimal] = Field(default=None, decimal_places=8)
    message: str = Field(max_length=500)
    severity: str = Field(default="info", max_length=20)
    acknowledged: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class DailyBalanceSnapshot(SQLModel, table=True):
    """
    Daily balance snapshots for reporting and auditing.
    """

    __tablename__ = "daily_balance_snapshots"

    snapshot_id: str = Field(primary_key=True, max_length=50)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)
    date: datetime = Field(index=True)
    opening_balance: Decimal = Field(decimal_places=8)
    closing_balance: Decimal = Field(decimal_places=8)
    total_credits: Decimal = Field(default=Decimal("0"), decimal_places=8)
    total_debits: Decimal = Field(default=Decimal("0"), decimal_places=8)
    transaction_count: int = Field(default=0)

    model_config = {"arbitrary_types_allowed": True}


class ServiceRegistryModel(SQLModel, table=True):
    """
    Service registry for the agent marketplace.

    Allows external developers to register billable services that agents
    can discover and pay for using the B2A billing infrastructure.
    """

    __tablename__ = "service_registry"

    service_id: str = Field(primary_key=True, max_length=100)
    name: str = Field(max_length=255)
    description: str = Field(default="", max_length=1000)
    owner_wallet_id: str = Field(
        max_length=50, foreign_key="wallets.wallet_id", index=True
    )
    owner_key: str = Field(max_length=255, index=True)
    category: str = Field(max_length=50, index=True)
    credits_per_unit: Decimal = Field(decimal_places=8)
    unit_name: str = Field(default="request", max_length=50)
    mcp_manifest: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    metadata_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"arbitrary_types_allowed": True}


class KYCVerificationModel(SQLModel, table=True):
    """
    KYC/Identity verification records for sponsor wallets.

    Tracks Stripe Identity verification sessions and their status.
    Only verified wallets can perform fiat top-ups.
    """

    __tablename__ = "kyc_verifications"

    verification_id: str = Field(primary_key=True, max_length=100)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)

    stripe_session_id: str = Field(max_length=100, unique=True, index=True)

    status: str = Field(max_length=30, default="pending")

    verification_type: str = Field(max_length=20, default="identity")

    document_type: Optional[str] = Field(default=None, max_length=30)

    first_verified_at: Optional[datetime] = Field(default=None)
    last_verified_at: Optional[datetime] = Field(default=None)

    rejection_reason: Optional[str] = Field(default=None, max_length=500)

    metadata_json: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"arbitrary_types_allowed": True}


class APIKeyModel(SQLModel, table=True):
    """
    API key registry for wallet authentication and key rotation.

    Supports multiple keys per wallet with rotation tracking.
    Keys can be rotated manually or automatically on suspicious activity.
    """

    __tablename__ = "api_keys"

    key_id: str = Field(primary_key=True, max_length=50)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)

    key_hash: str = Field(max_length=64, index=True)
    key_prefix: str = Field(max_length=8)

    status: str = Field(default="active", max_length=20)

    rotation_count: int = Field(default=0)
    last_rotated_at: Optional[datetime] = Field(default=None)

    last_used_at: Optional[datetime] = Field(default=None)
    last_used_ip: Optional[str] = Field(default=None, max_length=45)

    created_at: datetime = Field(default_factory=utc_now, index=True)
    expires_at: Optional[datetime] = Field(default=None)

    revoked_at: Optional[datetime] = Field(default=None)
    revoke_reason: Optional[str] = Field(default=None, max_length=255)

    metadata_json: Optional[str] = Field(default=None)

    model_config = {"arbitrary_types_allowed": True}


class TelemetryEventModel(SQLModel, table=True):
    """
    Time-series telemetry events for the Autonomous PM.

    Supplants the in-memory EventStore. On PostgreSQL with the TimescaleDB
    extension, the Alembic migration converts this into a hypertable keyed
    on ``event_timestamp`` so retention cleanup and time-range queries
    scale to large volumes.

    ``payload_json`` captures the full TelemetryEvent.metadata dict for
    fidelity — any field the application cares to filter on is promoted
    to a dedicated column for indexability.
    """

    __tablename__ = "telemetry_events"

    event_id: str = Field(primary_key=True, max_length=50)
    batch_id: str = Field(max_length=50, index=True)

    # Promoted fields — dedicated columns so filters don't pay a JSON cost.
    event_type: str = Field(max_length=20, index=True)
    severity: str = Field(max_length=20, index=True)
    source: str = Field(max_length=100, index=True)
    message: str = Field(default="", max_length=1000)
    stack_trace: Optional[str] = Field(default=None)

    # Full metadata dict preserved as JSON for anything not promoted.
    payload_json: Optional[str] = Field(default=None)

    # Two timestamps: when the event actually happened (from the client)
    # vs when we stored it (authoritative for retention).
    event_timestamp: Optional[datetime] = Field(default=None, index=True)
    ingested_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class IoTDeviceModel(SQLModel, table=True):
    """Registered IoT device state for the protocol bridge."""

    __tablename__ = "iot_devices"

    device_id: str = Field(primary_key=True, max_length=100)
    protocol: str = Field(max_length=20, index=True)
    broker_url: Optional[str] = Field(default=None, max_length=500)
    topic_acl_json: Optional[str] = Field(default=None)
    metadata_json: Optional[str] = Field(default=None)
    status: str = Field(default="registered", max_length=30, index=True)
    registered_at: datetime = Field(default_factory=utc_now, index=True)
    last_message_at: Optional[datetime] = Field(default=None)
    message_count: int = Field(default=0)

    model_config = {"arbitrary_types_allowed": True}


class IoTDeviceEventModel(SQLModel, table=True):
    """Append-only audit event for IoT bridge registry and message activity."""

    __tablename__ = "iot_device_events"

    event_id: str = Field(primary_key=True, max_length=64)
    device_id: str = Field(max_length=100, index=True)
    event_type: str = Field(max_length=30, index=True)
    topic: Optional[str] = Field(default=None, max_length=500)
    payload_json: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class OracleCrawlTargetModel(SQLModel, table=True):
    """Crawl target lifecycle row (pending → crawling → indexed|failed)."""

    __tablename__ = "oracle_crawl_targets"

    target_id: str = Field(primary_key=True, max_length=64)
    url: str = Field(max_length=2048, index=True)
    directory_type: str = Field(max_length=30, index=True)
    status: str = Field(max_length=20, index=True)
    api_id: Optional[str] = Field(default=None, max_length=64, index=True)
    queued_at: datetime = Field(default_factory=utc_now, index=True)
    crawled_at: Optional[datetime] = Field(default=None)
    raw_payload_hash: Optional[str] = Field(default=None, max_length=128)

    model_config = {"arbitrary_types_allowed": True}


class OracleIndexedAPIModel(SQLModel, table=True):
    """An indexed external API with compatibility metadata."""

    __tablename__ = "oracle_indexed_apis"

    api_id: str = Field(primary_key=True, max_length=64)
    url: str = Field(max_length=2048, index=True)
    name: str = Field(max_length=255)
    description: str = Field(default="", max_length=2000)
    directory_type: str = Field(max_length=30, index=True)
    compatibility_tier: str = Field(max_length=20, index=True)
    compatibility_score: float = Field(default=0.0, index=True)
    capabilities_json: Optional[str] = Field(default=None)
    tags_json: Optional[str] = Field(default=None)
    status: str = Field(max_length=20)
    last_crawled: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class OracleRegistrationModel(SQLModel, table=True):
    """One row per attempt to register our API in an external directory."""

    __tablename__ = "oracle_registrations"

    registration_id: str = Field(primary_key=True, max_length=64)
    directory_url: str = Field(max_length=2048, index=True)
    directory_type: str = Field(max_length=30, index=True)
    status: str = Field(max_length=20, index=True)
    message: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class OracleDiscoveryHitModel(SQLModel, table=True):
    """One row per inbound discovery hit for top-referrer aggregation."""

    __tablename__ = "oracle_discovery_hits"

    hit_id: str = Field(primary_key=True, max_length=64)
    referrer: str = Field(default="direct", max_length=2048, index=True)
    timestamp: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class AgentCommsMessageModel(SQLModel, table=True):
    """Durable agent-to-agent message row when SIMULATION_MODE_AGENT_COMMS is false."""

    __tablename__ = "agent_comms_messages"

    message_id: str = Field(primary_key=True, max_length=64)
    from_agent: str = Field(max_length=100, index=True)
    to_agent: str = Field(max_length=100, index=True)
    message_type: str = Field(max_length=30)
    priority: str = Field(max_length=20)
    subject: str = Field(default="", max_length=500)
    body_json: Optional[str] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None, max_length=100, index=True)
    reply_to: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(max_length=20, index=True)
    payload_hash: Optional[str] = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    delivered_at: Optional[datetime] = Field(default=None)

    model_config = {"arbitrary_types_allowed": True}


class SecurityScanModel(SQLModel, table=True):
    """Shared scan table for red_team (internal) and rtaas (external)."""

    __tablename__ = "security_scans"

    scan_id: str = Field(primary_key=True, max_length=64)
    scan_type: str = Field(max_length=20, index=True)
    tenant_id: Optional[str] = Field(default=None, max_length=100, index=True)

    targets_json: Optional[str] = Field(default=None)
    attack_categories_json: Optional[str] = Field(default=None)
    intensity: str = Field(default="standard", max_length=20)

    status: str = Field(max_length=20, index=True)
    total_tests_run: int = Field(default=0)
    total_passed: Optional[int] = Field(default=None)
    total_failed: Optional[int] = Field(default=None)
    security_score: float = Field(default=0.0)

    recommendations_json: Optional[str] = Field(default=None)

    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class SecurityVulnerabilityModel(SQLModel, table=True):
    """Shared vulnerability rows for both scan types."""

    __tablename__ = "security_vulnerabilities"

    vuln_id: str = Field(primary_key=True, max_length=64)
    scan_id: str = Field(
        max_length=64,
        foreign_key="security_scans.scan_id",
        index=True,
    )

    category: str = Field(max_length=50, index=True)
    severity: str = Field(max_length=20, index=True)
    title: str = Field(max_length=500)
    description: str = Field(default="", max_length=4000)

    endpoint: str = Field(max_length=2048)
    method: Optional[str] = Field(default=None, max_length=10)

    evidence_json: Optional[str] = Field(default=None)
    remediation: str = Field(default="", max_length=4000)
    remediation_status: str = Field(default="open", max_length=30)
    cwe_id: Optional[str] = Field(default=None, max_length=20)

    discovered_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class ContentPipelineModel(SQLModel, table=True):
    """Content factory pipeline instance."""

    __tablename__ = "content_pipelines"

    pipeline_id: str = Field(primary_key=True, max_length=64)
    title: str = Field(max_length=500)
    source_clip_id: Optional[str] = Field(default=None, max_length=100)
    source_url: Optional[str] = Field(default=None, max_length=2048)
    target_formats_json: Optional[str] = Field(default=None)
    brand_config_json: Optional[str] = Field(default=None)
    language: str = Field(default="en", max_length=10)
    auto_schedule: bool = Field(default=True)
    owner_key: str = Field(default="", max_length=255, index=True)
    status: str = Field(default="queued", max_length=30, index=True)
    hook_json: Optional[str] = Field(default=None)
    caption_style: str = Field(default="bold_impact", max_length=30)
    aspect_ratio: str = Field(default="9:16", max_length=10)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class ContentPieceModel(SQLModel, table=True):
    """One generated content piece. download_url holds the blob ref."""

    __tablename__ = "content_pieces"

    content_id: str = Field(primary_key=True, max_length=64)
    pipeline_id: str = Field(
        max_length=64,
        foreign_key="content_pipelines.pipeline_id",
        index=True,
    )
    format: str = Field(max_length=30, index=True)
    title: str = Field(max_length=500)
    description: Optional[str] = Field(default=None, max_length=2000)
    download_url: str = Field(max_length=2048)
    thumbnail_url: Optional[str] = Field(default=None, max_length=2048)
    duration_seconds: Optional[float] = Field(default=None)
    dimensions: Optional[str] = Field(default=None, max_length=30)
    file_size_bytes: Optional[int] = Field(default=None)
    status: str = Field(max_length=20, index=True)
    metadata_json: Optional[str] = Field(default=None)
    generated_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class ContentCampaignModel(SQLModel, table=True):
    """Top-level live campaign linking many pipelines + hooks."""

    __tablename__ = "content_campaigns"

    campaign_id: str = Field(primary_key=True, max_length=64)
    campaign_title: str = Field(max_length=500)
    source_url: str = Field(max_length=2048)
    hooks_json: Optional[str] = Field(default=None)
    pipeline_ids_json: Optional[str] = Field(default=None)
    status: str = Field(default="running", max_length=30, index=True)
    owner_key: str = Field(default="", max_length=255, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class ContentScheduleModel(SQLModel, table=True):
    """Persisted scheduler recommendations."""

    __tablename__ = "content_schedules"

    schedule_id: str = Field(primary_key=True, max_length=64)
    content_id: str = Field(
        max_length=64,
        foreign_key="content_pieces.content_id",
        index=True,
    )
    platform: str = Field(max_length=50, index=True)
    recommended_time: datetime = Field(index=True)
    confidence: float = Field(default=0.0)
    reasoning: str = Field(default="", max_length=2000)
    estimated_views: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class ContentFactoryGenerationModel(SQLModel, table=True):
    """LLM text generation row when ``SIMULATION_MODE_CONTENT_FACTORY`` is false."""

    __tablename__ = "content_factory_generations"

    content_id: str = Field(primary_key=True, max_length=36)
    prompt_hash: Optional[str] = Field(default=None, max_length=64, index=True)
    output_hash: Optional[str] = Field(default=None, max_length=64)
    model: Optional[str] = Field(default=None, max_length=128)
    provenance_json: Optional[str] = Field(default=None)
    output_text: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: Optional[datetime] = Field(default=None)

    model_config = {"arbitrary_types_allowed": True}


class KeyRotationLogModel(SQLModel, table=True):
    """
    Audit log for API key rotations.

    Tracks rotation history for security auditing and compliance.
    """

    __tablename__ = "key_rotation_logs"

    log_id: str = Field(primary_key=True, max_length=50)
    key_id: str = Field(max_length=50, index=True)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)

    rotation_type: str = Field(max_length=30)

    old_key_id: Optional[str] = Field(default=None, max_length=50)
    new_key_id: Optional[str] = Field(default=None, max_length=50)

    trigger_reason: str = Field(max_length=255)
    triggered_by: str = Field(max_length=50)

    ip_address: Optional[str] = Field(default=None, max_length=45)
    user_agent: Optional[str] = Field(default=None, max_length=500)

    created_at: datetime = Field(default_factory=utc_now, index=True)

    model_config = {"arbitrary_types_allowed": True}


class OptimizerTelemetryModel(SQLModel, table=True):
    """Planner telemetry rows for optimization and policy tuning."""

    __tablename__ = "optimizer_telemetry"

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utc_now, index=True)
    wallet_id: str = Field(max_length=64, index=True)
    agent_id: str = Field(max_length=64, index=True)
    task_id: Optional[str] = Field(default=None, max_length=100, index=True)
    request_id: Optional[str] = Field(default=None, max_length=100, index=True)
    endpoint: str = Field(max_length=128, index=True)
    action_features: Optional[str] = Field(default=None)
    latency_ms: Optional[int] = Field(default=None)
    credits_delta: Optional[Decimal] = Field(default=None, decimal_places=8)
    success: bool = Field(default=True)
    error_class: Optional[str] = Field(default=None, max_length=64)
    risk_flags: Optional[str] = Field(default=None)
    payload_hash: Optional[str] = Field(default=None, max_length=64, index=True)


class ControlPlaneAuditEventModel(SQLModel, table=True):
    """Durable control-plane audit event for agent operations."""

    __tablename__ = "control_plane_audit_events"

    event_id: str = Field(primary_key=True, max_length=50)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    # Per-wallet monotonic sequence: a stable ordering key for the hash chain so
    # equal/clock-skewed created_at values can't reorder the chain on read.
    seq: int = Field(default=0, index=True)
    event: str = Field(max_length=128, index=True)
    wallet_id: Optional[str] = Field(default=None, max_length=64, index=True)
    tool: Optional[str] = Field(default=None, max_length=128, index=True)
    endpoint: Optional[str] = Field(default=None, max_length=256, index=True)
    auth_source: Optional[str] = Field(default=None, max_length=32)
    key_id: Optional[str] = Field(default=None, max_length=64, index=True)
    policy_decision_id: Optional[str] = Field(default=None, max_length=64, index=True)
    request_id: Optional[str] = Field(default=None, max_length=100, index=True)
    ok: bool = Field(default=True, index=True)
    error: Optional[str] = Field(default=None)
    metadata_json: Optional[str] = Field(default=None)
    payload_hash: Optional[str] = Field(default=None, max_length=64, index=True)
    previous_hash: Optional[str] = Field(default=None, max_length=64)
    chain_hash: Optional[str] = Field(default=None, max_length=64, index=True)
    signature: Optional[str] = Field(default=None)
    signature_key_id: Optional[str] = Field(
        default=None,
        max_length=64,
        foreign_key="signing_keys.key_id",
        index=True,
    )


class AuditChainHeadModel(SQLModel, table=True):
    """Per-wallet head pointer for the audit hash chain.

    A single row per wallet, locked FOR UPDATE during an append, serializes
    concurrent writers so they cannot read the same predecessor and fork the
    chain. ``wallet_key`` is the wallet id, or "" for wallet-less events.
    """

    __tablename__ = "audit_chain_heads"

    wallet_key: str = Field(primary_key=True, max_length=64)
    last_chain_hash: Optional[str] = Field(default=None, max_length=64)
    last_seq: int = Field(default=0)
    updated_at: datetime = Field(default_factory=utc_now)


class SigningKeyModel(SQLModel, table=True):
    """Public signing-key metadata for permits, receipts, and audit events."""

    __tablename__ = "signing_keys"

    key_id: str = Field(primary_key=True, max_length=64)
    alg: str = Field(default="Ed25519", max_length=20)
    public_key_b64: str
    status: str = Field(default="active", max_length=20, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    activated_at: Optional[datetime] = Field(default=None)
    retired_at: Optional[datetime] = Field(default=None)


class PermitModel(SQLModel, table=True):
    """Signed wallet-scoped authority for a governed agent action."""

    __tablename__ = "permits"
    __table_args__ = (
        UniqueConstraint("permit_id", "nonce", name="uq_permits_permit_nonce"),
    )

    permit_id: str = Field(primary_key=True, max_length=64)
    issuer_wallet_id: str = Field(
        max_length=50,
        foreign_key="wallets.wallet_id",
        index=True,
    )
    subject_wallet_id: str = Field(
        max_length=50,
        foreign_key="wallets.wallet_id",
        index=True,
    )
    subject_key_id: Optional[str] = Field(
        default=None,
        max_length=50,
        foreign_key="api_keys.key_id",
        index=True,
    )
    scopes_json: str
    allowed_tools_json: str
    max_credits: Decimal = Field(decimal_places=8)
    spent_credits: Decimal = Field(default=Decimal("0"), decimal_places=8)
    expires_at: datetime = Field(index=True)
    nonce: str = Field(max_length=64, index=True)
    status: str = Field(default="active", max_length=20, index=True)
    signature: str
    key_id: str = Field(max_length=64, foreign_key="signing_keys.key_id", index=True)
    issued_at: datetime = Field(default_factory=utc_now, index=True)
    revoked_at: Optional[datetime] = Field(default=None)
    # Last time budget was reserved/released; used to distinguish a live
    # in-flight reservation from one orphaned by a crash during reconciliation.
    updated_at: Optional[datetime] = Field(default=None, index=True)

    model_config = {"arbitrary_types_allowed": True}


class ReceiptModel(SQLModel, table=True):
    """Signed receipt for a governed MCP invocation attempt."""

    __tablename__ = "receipts"

    receipt_id: str = Field(primary_key=True, max_length=64)
    permit_id: str = Field(max_length=64, foreign_key="permits.permit_id", index=True)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)
    key_id: Optional[str] = Field(default=None, max_length=50, index=True)
    tool: str = Field(max_length=128, index=True)
    request_hash: str = Field(max_length=64, index=True)
    response_hash: Optional[str] = Field(default=None, max_length=64)
    ledger_entry_id: Optional[str] = Field(
        default=None,
        max_length=50,
        foreign_key="ledger_entries.entry_id",
        index=True,
    )
    credits_authorized: Decimal = Field(decimal_places=8)
    credits_charged: Decimal = Field(default=Decimal("0"), decimal_places=8)
    outcome: str = Field(max_length=32, index=True)
    audit_event_id: Optional[str] = Field(
        default=None,
        max_length=50,
        foreign_key="control_plane_audit_events.event_id",
        index=True,
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)
    signature: str
    signature_key_id: str = Field(
        max_length=64,
        foreign_key="signing_keys.key_id",
        index=True,
    )

    model_config = {"arbitrary_types_allowed": True}


class IdempotencyRecordModel(SQLModel, table=True):
    """Wallet-scoped replay protection for state-changing trust endpoints."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "endpoint",
            "idempotency_key",
            name="uq_idempotency_wallet_endpoint_key",
        ),
    )

    record_id: str = Field(primary_key=True, max_length=64)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)
    endpoint: str = Field(max_length=256, index=True)
    idempotency_key: str = Field(max_length=128, index=True)
    request_hash: str = Field(max_length=64)
    response_reference: Optional[str] = Field(default=None, max_length=128)
    response_json: Optional[str] = Field(default=None)
    status_code: int = Field(default=200)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    expires_at: Optional[datetime] = Field(default=None)


class PolicyBundleModel(SQLModel, table=True):
    """Wallet-scoped execution policy bundle."""

    __tablename__ = "policy_bundles"

    policy_id: str = Field(primary_key=True, max_length=64)
    wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)
    name: str = Field(max_length=255)
    allowed_tools_json: Optional[str] = Field(default=None)
    allowed_service_categories_json: Optional[str] = Field(default=None)
    max_cost_per_action: Optional[Decimal] = Field(default=None, decimal_places=8)
    daily_spend_limit: Optional[Decimal] = Field(default=None, decimal_places=8)
    require_real_effects: bool = Field(default=False)
    risk_tier: str = Field(default="medium", max_length=20)
    human_approval_required: bool = Field(default=False)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"arbitrary_types_allowed": True}
