"""
SQLModel database models for Agent Middleware API.
Defines normalized tables for wallets, ledger entries, and billing alerts.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import SQLModel, Field


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
    balance: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), decimal_places=8)
    lifetime_credits: Decimal = Field(default=Decimal("0"), decimal_places=8)
    lifetime_debits: Decimal = Field(default=Decimal("0"), decimal_places=8)

    # Hierarchy fields (for agent/child wallets)
    parent_wallet_id: Optional[str] = Field(default=None, foreign_key="wallets.wallet_id", index=True)
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True


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
    balance_after: Decimal = Field(ge=Decimal("0"), decimal_places=8)

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
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)

    class Config:
        arbitrary_types_allowed = True


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
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    class Config:
        arbitrary_types_allowed = True


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

    class Config:
        arbitrary_types_allowed = True


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
    owner_wallet_id: str = Field(max_length=50, foreign_key="wallets.wallet_id", index=True)
    owner_key: str = Field(max_length=255, index=True)
    category: str = Field(max_length=50, index=True)
    credits_per_unit: Decimal = Field(decimal_places=8)
    unit_name: str = Field(default="request", max_length=50)
    mcp_manifest: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    metadata_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True


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

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True


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

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: Optional[datetime] = Field(default=None)

    revoked_at: Optional[datetime] = Field(default=None)
    revoke_reason: Optional[str] = Field(default=None, max_length=255)

    metadata_json: Optional[str] = Field(default=None)

    class Config:
        arbitrary_types_allowed = True


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

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    class Config:
        arbitrary_types_allowed = True
