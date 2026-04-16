"""
Conversion utilities between SQLModel database rows and Pydantic API schemas.
"""

import json
from typing import Any

from ..schemas.billing import (
    WalletResponse,
    WalletType,
    WalletStatus,
    LedgerEntry,
    LedgerAction,
    ServiceCategory,
    BillingAlert,
    AlertType,
    AlertSeverity,
    KYCStatus,
)
from .models import WalletModel, LedgerEntryModel, BillingAlertModel


def wallet_model_to_response(
    wallet: WalletModel,
) -> WalletResponse:
    """Convert a WalletModel to a WalletResponse Pydantic schema."""
    metadata = {}
    if wallet.metadata_json:
        try:
            metadata = json.loads(wallet.metadata_json)
        except json.JSONDecodeError:
            pass

    kyc_status_str = wallet.kyc_status or "not_required"
    try:
        kyc_status = KYCStatus(kyc_status_str)
    except ValueError:
        kyc_status = KYCStatus.NOT_REQUIRED

    return WalletResponse(
        wallet_id=wallet.wallet_id,
        wallet_type=WalletType(wallet.wallet_type),
        owner_name=wallet.owner_name,
        email=wallet.email,
        balance=wallet.balance,
        lifetime_credits=wallet.lifetime_credits,
        lifetime_debits=wallet.lifetime_debits,
        sponsor_wallet_id=wallet.parent_wallet_id,
        agent_id=wallet.agent_id,
        child_agent_id=wallet.child_agent_id,
        max_spend=wallet.max_spend,
        task_description=wallet.task_description,
        ttl_seconds=wallet.ttl_seconds,
        daily_limit=wallet.daily_limit,
        auto_refill=wallet.auto_refill,
        auto_refill_threshold=wallet.auto_refill_threshold,
        auto_refill_amount=wallet.auto_refill_amount,
        status=WalletStatus(wallet.status),
        kyc_status=kyc_status,
        created_at=wallet.created_at,
        metadata=metadata,
    )


def ledger_entry_model_to_schema(
    entry: LedgerEntryModel,
) -> LedgerEntry:
    """Convert a LedgerEntryModel to a LedgerEntry Pydantic schema."""
    metadata = {}
    if entry.metadata_json:
        try:
            metadata = json.loads(entry.metadata_json)
        except json.JSONDecodeError:
            pass

    return LedgerEntry(
        entry_id=entry.entry_id,
        wallet_id=entry.wallet_id,
        action=LedgerAction(entry.action),
        amount=entry.amount,
        balance_after=entry.balance_after,
        service_category=(
            ServiceCategory(entry.service_category)
            if entry.service_category
            else None
        ),
        description=entry.description,
        request_path=entry.request_path,
        compute_cost=entry.compute_cost,
        margin=entry.margin,
        timestamp=entry.timestamp,
        metadata=metadata,
    )


def billing_alert_model_to_schema(
    alert: BillingAlertModel,
) -> BillingAlert:
    """Convert a BillingAlertModel to a BillingAlert Pydantic schema."""
    return BillingAlert(
        alert_id=alert.alert_id,
        wallet_id=alert.wallet_id,
        alert_type=AlertType(alert.alert_type),
        threshold_amount=alert.threshold_amount,
        current_balance=alert.current_balance,
        message=alert.message,
        severity=AlertSeverity(alert.severity),
        acknowledged=alert.acknowledged,
        created_at=alert.created_at,
    )


def metadata_dict_to_json(metadata: dict[str, Any] | None) -> str | None:
    """Convert a metadata dict to JSON string for database storage."""
    if not metadata:
        return None
    return json.dumps(metadata, default=str)


def parse_metadata_json(metadata_json: str | None) -> dict[str, Any]:
    """Parse metadata JSON string to dict."""
    if not metadata_json:
        return {}
    try:
        return json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
