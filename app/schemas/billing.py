"""
Schemas for Agent Financial Gateways (Service Pillar 8).

Two-tiered wallet system:
- Human Sponsor Layer: Fiat ingestion via Stripe/payment rails → ecosystem credits
- Agent Wallet Layer: Pre-paid, programmatic wallets for autonomous spending

IMPORTANT: While the API accepts/returns float for backward compatibility,
the service layer uses Decimal for all monetary calculations to avoid
floating-point precision errors (e.g., 0.1 + 0.2 ≠ 0.3 with floats).
"""

from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
import re


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WalletType(str, Enum):
    """Wallet types in the three-tier system."""
    SPONSOR = "sponsor"
    AGENT = "agent"
    CHILD = "child"


class WalletStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    FROZEN = "frozen"
    CLOSED = "closed"
    PENDING_KYC = "pending_kyc"


class LedgerAction(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"
    TRANSFER = "transfer"
    REFUND = "refund"
    ARBITRAGE_MARGIN = "arbitrage_margin"


class ServiceCategory(str, Enum):
    IOT_BRIDGE = "iot_bridge"
    TELEMETRY_PM = "telemetry_pm"
    MEDIA_ENGINE = "media_engine"
    AGENT_COMMS = "agent_comms"
    CONTENT_FACTORY = "content_factory"
    RED_TEAM = "red_team"
    ORACLE = "oracle"
    PLATFORM_FEE = "platform_fee"
    SWARM_DELEGATION = "swarm_delegation"
    PROTOCOL_GEN = "protocol_gen"
    SANDBOX = "sandbox"
    RTAAS = "rtaas"


class TopUpStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class AlertType(str, Enum):
    LOW_BALANCE = "low_balance"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    BUDGET_EXCEEDED = "budget_exceeded"
    ANOMALOUS_SPEND = "anomalous_spend"
    KYC_PENDING = "kyc_pending"
    KYC_REJECTED = "kyc_rejected"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


class KYCStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class APIKeyStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


class RotationType(str, Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    EMERGENCY = "emergency"
    SCHEDULED = "scheduled"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Wallet Schemas
# ---------------------------------------------------------------------------

SAFE_WALLET_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class CreateSponsorWalletRequest(BaseModel):
    """Create a human sponsor (liability sink) root account."""
    sponsor_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Human or organization name for the liability sink.",
        examples=["Acme Corp Engineering"],
    )
    email: str = Field(
        ...,
        description="Contact email for billing alerts and top-up requests.",
        examples=["billing@acme.com"],
    )
    initial_credits: float = Field(
        default=0.0,
        ge=0,
        description="Initial credit balance (in ecosystem credits).",
    )
    currency: str = Field(
        default="USD",
        description="Fiat currency for external payment rails.",
    )
    require_kyc: bool | None = Field(
        default=None,
        description="Require KYC verification before allowing fiat top-ups. Defaults to system setting.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary metadata (Stripe customer ID, org info, etc.).",
    )


class CreateAgentWalletRequest(BaseModel):
    """Provision a pre-paid agent wallet under a sponsor."""
    sponsor_wallet_id: str = Field(..., description="ID of the sponsor wallet funding this agent.")
    agent_id: str = Field(..., description="Agent ID from the comms registry.")
    budget_credits: float = Field(..., gt=0, description="Credits to provision from the sponsor's balance.")
    daily_limit: float | None = Field(default=None, ge=0, description="Optional daily spend cap.")
    auto_refill: bool = Field(default=False, description="Auto-refill from sponsor when balance drops below threshold.")
    auto_refill_threshold: float = Field(default=100.0, ge=0, description="Refill trigger threshold.")
    auto_refill_amount: float = Field(default=1000.0, ge=0, description="Amount to refill.")


class CreateChildWalletRequest(BaseModel):
    """Spawn a sub-agent child wallet from an agent wallet."""
    parent_wallet_id: str = Field(..., description="ID of the parent agent wallet funding this child.")
    child_agent_id: str = Field(..., description="Identifier for the child sub-agent.")
    budget_credits: float = Field(..., gt=0, description="Credits to provision from parent's balance.")
    max_spend: float = Field(..., gt=0, description="Hard lifetime spend cap in credits.")
    task_description: str = Field(default="", description="What this child agent is supposed to accomplish.")
    ttl_seconds: int | None = Field(default=None, gt=0, description="Time-to-live in seconds.")
    auto_reclaim: bool = Field(default=True, description="Reclaim unspent credits when child completes.")


class ChildWalletResponse(BaseModel):
    """Child wallet details with parent lineage."""
    wallet_id: str
    wallet_type: WalletType
    parent_wallet_id: str | None = None
    child_agent_id: str | None = None
    balance: float
    max_spend: float | None = None
    spent: float = 0.0
    task_description: str = ""
    ttl_seconds: int | None = None
    auto_reclaim: bool = True
    status: WalletStatus
    created_at: datetime


class SwarmBudgetSummary(BaseModel):
    """Hierarchical budget summary for an agent's child swarm."""
    parent_wallet_id: str
    parent_balance: float
    total_delegated: float
    total_reclaimed: float
    active_children: int
    completed_children: int
    frozen_children: int
    children: list["WalletResponse"]


class ReclaimResponse(BaseModel):
    """Result of reclaiming unspent credits from a child wallet."""
    child_wallet_id: str
    parent_wallet_id: str
    credits_reclaimed: float
    parent_balance_after: float
    child_status: WalletStatus


class WalletResponse(BaseModel):
    """Wallet details."""
    wallet_id: str
    wallet_type: WalletType
    owner_name: str | None = None
    email: str | None = None
    balance: float = Field(..., description="Current credit balance.")
    lifetime_credits: float = Field(..., description="Total credits ever deposited.")
    lifetime_debits: float = Field(..., description="Total credits ever consumed.")
    status: WalletStatus
    kyc_status: KYCStatus = Field(default=KYCStatus.NOT_REQUIRED)
    daily_limit: float | None = None
    auto_refill: bool = False
    auto_refill_threshold: float | None = None
    auto_refill_amount: float | None = None
    sponsor_wallet_id: str | None = None
    agent_id: str | None = None
    child_agent_id: str | None = None
    max_spend: float | None = None
    task_description: str | None = None
    ttl_seconds: int | None = None
    created_at: datetime
    metadata: dict = Field(default_factory=dict)


class WalletListResponse(BaseModel):
    wallets: list[WalletResponse]
    total: int


# ---------------------------------------------------------------------------
# Ledger Schemas
# ---------------------------------------------------------------------------

class LedgerEntry(BaseModel):
    """A single atomic transaction in the billing ledger."""
    entry_id: str
    wallet_id: str
    action: LedgerAction
    amount: float = Field(..., description="Credit amount (positive=credit, negative=debit).")
    balance_after: float = Field(..., description="Wallet balance after this transaction.")
    service_category: ServiceCategory | None = None
    description: str = ""
    request_path: str | None = None
    compute_cost: float | None = None
    margin: float | None = None
    timestamp: datetime
    metadata: dict = Field(default_factory=dict)


class LedgerResponse(BaseModel):
    """Paginated ledger entries."""
    entries: list[LedgerEntry]
    total: int
    wallet_id: str
    period_credits: float
    period_debits: float


# ---------------------------------------------------------------------------
# Top-Up / Payment Schemas
# ---------------------------------------------------------------------------

class TopUpRequest(BaseModel):
    """Request to add credits to a sponsor wallet via fiat payment."""
    wallet_id: str = Field(..., description="Sponsor wallet to top up.")
    amount_fiat: float = Field(..., gt=0, description="Amount in fiat currency (e.g., USD).")
    payment_method: str = Field(default="stripe", description="Payment rail to use.")
    payment_token: str | None = Field(default=None, description="Payment method token.")


class TopUpResponse(BaseModel):
    """Result of a top-up request."""
    top_up_id: str
    wallet_id: str
    amount_fiat: float
    credits_added: float
    exchange_rate: float
    status: TopUpStatus
    payment_url: str | None = None


class InsufficientFundsResponse(BaseModel):
    """Structured 402 Payment Required response."""
    error: str = "insufficient_funds"
    wallet_id: str
    current_balance: float
    required_amount: float
    shortfall: float
    top_up_url: str
    message: str = "Wallet balance insufficient."


# ---------------------------------------------------------------------------
# Metering & Pricing Schemas
# ---------------------------------------------------------------------------

class ServicePricing(BaseModel):
    """Per-action pricing for a service category."""
    service_category: ServiceCategory
    unit: str
    credits_per_unit: float
    description: str = ""


class PricingTableResponse(BaseModel):
    """Full pricing table for all services."""
    pricing: list[ServicePricing]
    exchange_rate: float
    last_updated: datetime


# ---------------------------------------------------------------------------
# Arbitrage / Margin Schemas
# ---------------------------------------------------------------------------

class ArbitrageReport(BaseModel):
    """Swarm arbitrage profitability report."""
    period: str
    total_revenue: float
    total_compute_cost: float
    gross_margin: float
    margin_percentage: float
    by_service: dict[str, dict] = Field(default_factory=dict)
    top_profitable_actions: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Alert Schemas
# ---------------------------------------------------------------------------

class BillingAlert(BaseModel):
    """Billing alert for sponsors or agents."""
    alert_id: str
    alert_type: AlertType
    wallet_id: str
    message: str
    threshold_amount: float | None = None
    current_balance: float | None = None
    severity: AlertSeverity = AlertSeverity.INFO
    acknowledged: bool = False
    created_at: datetime


class AlertListResponse(BaseModel):
    alerts: list[BillingAlert]
    total: int
    unacknowledged: int


class RegisterServiceRequest(BaseModel):
    """Register a new billable service in the marketplace."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    category: ServiceCategory
    credits_per_unit: float = Field(..., gt=0)
    unit_name: str = Field(default="request", max_length=50)
    mcp_manifest: dict | None = None


class ServiceRegistration(BaseModel):
    """A registered billable service in the marketplace."""
    service_id: str
    name: str
    description: str
    owner_wallet_id: str
    category: ServiceCategory
    credits_per_unit: float
    unit_name: str
    mcp_manifest: dict | None = None
    is_active: bool
    created_at: datetime


class TransferResponse(BaseModel):
    """Response for a wallet-to-wallet transfer."""
    transfer_id: str
    from_wallet_id: str
    to_wallet_id: str
    amount: float
    from_balance_after: float
    to_balance_after: float
    status: str


class CreateKYCSessionRequest(BaseModel):
    """Request to create a KYC verification session."""
    wallet_id: str = Field(..., description="Wallet ID requiring KYC verification.")
    return_url: str = Field(
        ...,
        description="URL to redirect after verification completes.",
        examples=["https://yourapp.com/kyc-callback"],
    )
    document_type: str = Field(
        default="document",
        description="Type of document to verify (passport, driver_license, id_card).",
    )


class KYCSessionResponse(BaseModel):
    """Response with Stripe Identity session details."""
    verification_id: str
    wallet_id: str
    session_id: str
    session_url: str
    status: KYCStatus
    created_at: datetime
    expires_at: datetime


class KYCStatusResponse(BaseModel):
    """Current KYC verification status for a wallet."""
    wallet_id: str
    kyc_status: KYCStatus
    verification_id: str | None = None
    stripe_session_id: str | None = None
    last_verified_at: datetime | None = None
    rejection_reason: str | None = None
    requires_verification: bool = False
    message: str = ""


class KYCVerificationDetails(BaseModel):
    """Detailed verification information."""
    verification_id: str
    wallet_id: str
    status: KYCStatus
    stripe_session_id: str | None = None
    document_type: str | None = None
    first_verified_at: datetime | None = None
    last_verified_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class CreateAPIKeyRequest(BaseModel):
    """Request to create a new API key for a wallet."""
    wallet_id: str = Field(..., description="Wallet ID to create key for.")
    key_name: str = Field(
        default="default",
        max_length=50,
        description="Human-readable name for this key.",
    )
    expires_in_days: int | None = Field(
        default=None,
        gt=0,
        description="Optional expiration in days. None = no expiration.",
    )
    max_uses: int | None = Field(
        default=None,
        gt=0,
        description="Optional max uses. None = unlimited.",
    )


class APIKeyResponse(BaseModel):
    """API key response with masked key for display."""
    key_id: str
    wallet_id: str
    key_prefix: str
    masked_key: str
    status: APIKeyStatus
    key_name: str = "default"
    rotation_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime
    expires_at: datetime | None = None


class APIKeyWithSecret(BaseModel):
    """API key response including the actual key (only shown once)."""
    key_id: str
    wallet_id: str
    api_key: str
    key_prefix: str
    status: APIKeyStatus
    key_name: str = "default"
    created_at: datetime
    expires_at: datetime | None = None
    warning: str = "Store this key securely. It will not be shown again."


class RotateAPIKeyRequest(BaseModel):
    """Request to rotate an API key."""
    wallet_id: str = Field(..., description="Wallet ID owning the key.")
    key_id: str | None = Field(
        default=None,
        description="Specific key ID to rotate. None = create new key only.",
    )
    revoke_old: bool = Field(
        default=False,
        description="Whether to revoke the old key after rotation.",
    )
    reason: str = Field(
        default="manual_rotation",
        max_length=255,
        description="Reason for rotation.",
    )


class RotationResponse(BaseModel):
    """Response after key rotation."""
    rotation_id: str
    wallet_id: str
    old_key_id: str | None = None
    new_key: APIKeyWithSecret | None = None
    rotation_type: RotationType
    revoked_keys: list[str] = []
    created_at: datetime


class APIKeyListResponse(BaseModel):
    """List of API keys for a wallet."""
    wallet_id: str
    keys: list[APIKeyResponse]
    total_active: int
    total_revoked: int


class KeyRotationLogEntry(BaseModel):
    """Audit log entry for key rotation."""
    log_id: str
    key_id: str
    wallet_id: str
    rotation_type: RotationType
    old_key_id: str | None = None
    new_key_id: str | None = None
    trigger_reason: str
    triggered_by: str
    created_at: datetime


class EmergencyKeyRevocationRequest(BaseModel):
    """Request to immediately revoke all keys for a wallet."""
    wallet_id: str = Field(..., description="Wallet ID to revoke keys for.")
    reason: str = Field(
        default="security_incident",
        max_length=255,
        description="Reason for emergency revocation.",
    )
    create_new_key: bool = Field(
        default=True,
        description="Whether to create a new emergency key.",
    )


class SandboxCommitRequest(BaseModel):
    """Request to commit a sandbox session to real billing."""
    session_id: str = Field(..., description="Sandbox session ID to commit.")


class SandboxCommitResponse(BaseModel):
    """Response after committing a sandbox session."""
    session_id: str
    wallet_id: str
    committed_charges: int
    total_credits_deducted: float
    real_balance_before: float
    real_balance_after: float
    ledger_entries: list[dict]
    success: bool
    message: str


class SandboxRevertResponse(BaseModel):
    """Response after reverting a sandbox session."""
    session_id: str
    wallet_id: str
    reverted: bool
    message: str
