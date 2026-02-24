"""
Schemas for Agent Financial Gateways (Service Pillar 8).

Two-tiered wallet system:
- Human Sponsor Layer: Fiat ingestion via Stripe/payment rails → ecosystem credits
- Agent Wallet Layer: Pre-paid, programmatic wallets for autonomous spending

Agents can't hold credit cards, sign contracts, or pass 2FA.
Every agent needs a human "liability sink" who provisions its budget.

Billing model: Per-action micro-metering, not monthly SaaS subscriptions.
Agents transact at superhuman speed — the ledger must keep up.
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
    SPONSOR = "sponsor"     # Human-owned root account (the liability sink)
    AGENT = "agent"         # Machine-owned pre-paid wallet
    CHILD = "child"         # Sub-agent wallet spawned by an agent (spend-capped)


class WalletStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"    # Insufficient funds
    FROZEN = "frozen"          # Manual hold by sponsor
    CLOSED = "closed"


class LedgerAction(str, Enum):
    """Types of ledger entries."""
    CREDIT = "credit"             # Funds added (top-up, sponsor provision)
    DEBIT = "debit"               # Funds consumed (API usage)
    TRANSFER = "transfer"         # Sponsor → agent wallet
    REFUND = "refund"             # Reversed charge
    ARBITRAGE_MARGIN = "arbitrage_margin"  # Profit booked on swarm routing


class ServiceCategory(str, Enum):
    """Billable service categories mapped to our pillars."""
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
        description="Initial credit balance (in ecosystem credits). 1 credit ≈ $0.001 USD.",
    )
    currency: str = Field(
        default="USD",
        description="Fiat currency for external payment rails.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary metadata (Stripe customer ID, org info, etc.).",
    )


class CreateAgentWalletRequest(BaseModel):
    """Provision a pre-paid agent wallet under a sponsor."""
    sponsor_wallet_id: str = Field(
        ...,
        description="ID of the sponsor wallet funding this agent.",
    )
    agent_id: str = Field(
        ...,
        description="Agent ID from the comms registry (or external agent identifier).",
    )
    budget_credits: float = Field(
        ...,
        gt=0,
        description="Credits to provision from the sponsor's balance.",
        examples=[10000.0],
    )
    daily_limit: float | None = Field(
        None,
        ge=0,
        description="Optional daily spend cap in credits. Null = unlimited.",
    )
    auto_refill: bool = Field(
        default=False,
        description="Auto-refill from sponsor when balance drops below threshold.",
    )
    auto_refill_threshold: float = Field(
        default=100.0,
        ge=0,
        description="Refill trigger threshold (credits).",
    )
    auto_refill_amount: float = Field(
        default=1000.0,
        ge=0,
        description="Amount to refill (credits).",
    )


class CreateChildWalletRequest(BaseModel):
    """Spawn a sub-agent child wallet from an agent wallet.

    Enables hierarchical swarm budgeting: a master agent building a tool
    spins up specialized sub-agents, each with a micro-budget and hard
    spend cap. The child wallet draws from the parent agent's balance.
    """
    parent_wallet_id: str = Field(
        ...,
        description="ID of the parent agent wallet funding this child.",
    )
    child_agent_id: str = Field(
        ...,
        description="Identifier for the child sub-agent (e.g., 'code-writer-01').",
    )
    budget_credits: float = Field(
        ...,
        gt=0,
        description="Credits to provision from parent's balance.",
        examples=[2000.0],
    )
    max_spend: float = Field(
        ...,
        gt=0,
        description="Hard lifetime spend cap in credits. Wallet freezes at this limit.",
        examples=[2000.0],
    )
    task_description: str = Field(
        default="",
        description="What this child agent is supposed to accomplish.",
        examples=["Write unit tests for the scraper module"],
    )
    ttl_seconds: int | None = Field(
        None,
        gt=0,
        description="Time-to-live in seconds. Wallet auto-freezes after expiry.",
    )
    auto_reclaim: bool = Field(
        default=True,
        description="Reclaim unspent credits back to parent when child completes or expires.",
    )


class ChildWalletResponse(BaseModel):
    """Child wallet details with parent lineage."""
    wallet_id: str
    wallet_type: WalletType
    parent_wallet_id: str
    child_agent_id: str
    balance: float
    max_spend: float
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
    children: list[ChildWalletResponse]


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
    owner_name: str
    balance: float = Field(..., description="Current credit balance.")
    lifetime_credits: float = Field(..., description="Total credits ever deposited.")
    lifetime_debits: float = Field(..., description="Total credits ever consumed.")
    status: WalletStatus
    daily_limit: float | None = None
    daily_spent: float = 0.0
    sponsor_wallet_id: str | None = None
    agent_id: str | None = None
    auto_refill: bool = False
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
    amount: float = Field(
        ...,
        description="Credit amount. Positive for credits/refunds, negative for debits.",
    )
    balance_after: float = Field(
        ...,
        description="Wallet balance after this transaction.",
    )
    service_category: ServiceCategory | None = None
    description: str = ""
    request_path: str | None = Field(
        None,
        description="API path that triggered this charge (e.g., POST /v1/iot/devices).",
    )
    compute_cost: float | None = Field(
        None,
        description="Internal compute cost (for arbitrage margin calculation).",
    )
    margin: float | None = Field(
        None,
        description="Profit margin = charged amount - compute cost.",
    )
    timestamp: datetime
    metadata: dict = Field(default_factory=dict)


class LedgerResponse(BaseModel):
    """Paginated ledger entries."""
    entries: list[LedgerEntry]
    total: int
    wallet_id: str
    period_credits: float = Field(..., description="Total credits in this period.")
    period_debits: float = Field(..., description="Total debits in this period.")


# ---------------------------------------------------------------------------
# Top-Up / Payment Schemas
# ---------------------------------------------------------------------------

class TopUpRequest(BaseModel):
    """Request to add credits to a sponsor wallet via fiat payment."""
    wallet_id: str = Field(
        ...,
        description="Sponsor wallet to top up.",
    )
    amount_fiat: float = Field(
        ...,
        gt=0,
        description="Amount in fiat currency (e.g., USD).",
        examples=[50.00],
    )
    payment_method: str = Field(
        default="stripe",
        description="Payment rail to use.",
    )
    payment_token: str | None = Field(
        None,
        description="Payment method token from the fiat provider (Stripe token, etc.).",
    )


class TopUpResponse(BaseModel):
    """Result of a top-up request."""
    top_up_id: str
    wallet_id: str
    amount_fiat: float
    credits_added: float = Field(
        ...,
        description="Credits deposited (fiat × exchange rate).",
    )
    exchange_rate: float = Field(
        ...,
        description="Credits per fiat unit. Default: 1000 credits per $1 USD.",
    )
    status: TopUpStatus
    payment_url: str | None = Field(
        None,
        description="URL for completing payment (if async checkout flow).",
    )


class InsufficientFundsResponse(BaseModel):
    """Structured 402 Payment Required response for agents.

    When an agent's wallet is empty, this tells the agent (or its sponsor)
    exactly what happened and how to fix it programmatically.
    """
    error: str = "insufficient_funds"
    wallet_id: str
    current_balance: float
    required_amount: float
    shortfall: float
    top_up_url: str = Field(
        ...,
        description="Programmatic webhook the agent can forward to its sponsor.",
    )
    message: str = Field(
        default="Wallet balance insufficient. Forward top_up_url to your sponsor for provisioning.",
    )


# ---------------------------------------------------------------------------
# Metering & Pricing Schemas
# ---------------------------------------------------------------------------

class ServicePricing(BaseModel):
    """Per-action pricing for a service category."""
    service_category: ServiceCategory
    unit: str = Field(
        ...,
        description="Billing unit (e.g., 'request', 'ms', 'token', 'frame', 'byte').",
    )
    credits_per_unit: float = Field(
        ...,
        gt=0,
        description="Cost in credits per unit.",
    )
    description: str = ""


class PricingTableResponse(BaseModel):
    """Full pricing table for all services."""
    pricing: list[ServicePricing]
    exchange_rate: float = Field(
        ...,
        description="Credits per $1 USD.",
    )
    last_updated: datetime


# ---------------------------------------------------------------------------
# Arbitrage / Margin Schemas
# ---------------------------------------------------------------------------

class ArbitrageReport(BaseModel):
    """Swarm arbitrage profitability report."""
    period: str = Field(
        ...,
        description="Reporting period (e.g., '2026-02-22 to 2026-02-23').",
    )
    total_revenue: float = Field(
        ...,
        description="Total credits charged to agents.",
    )
    total_compute_cost: float = Field(
        ...,
        description="Total internal compute cost.",
    )
    gross_margin: float = Field(
        ...,
        description="Revenue - compute cost.",
    )
    margin_percentage: float = Field(
        ...,
        description="Gross margin as percentage of revenue.",
    )
    by_service: dict[str, dict] = Field(
        default_factory=dict,
        description="Margin breakdown per service category.",
    )
    top_profitable_actions: list[dict] = Field(
        default_factory=list,
        description="Highest-margin individual actions.",
    )


# ---------------------------------------------------------------------------
# Alert Schemas
# ---------------------------------------------------------------------------

class BillingAlert(BaseModel):
    """Billing alert for sponsors or agents."""
    alert_id: str
    alert_type: AlertType
    wallet_id: str
    message: str
    threshold: float | None = None
    current_value: float | None = None
    timestamp: datetime
    acknowledged: bool = False


class AlertListResponse(BaseModel):
    alerts: list[BillingAlert]
    total: int
    unacknowledged: int
