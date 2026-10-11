"""Historical wallet-to-account attribution using exact wallet ownership."""

from __future__ import annotations

from datetime import datetime

from app.services.operation_insights.contracts import (
    AccountAttribution,
    AccountMapping,
    _utc,
)


def attribute(
    wallet_id: str | None, at: datetime | None, mapping: AccountMapping
) -> AccountAttribution:
    """Resolve one wallet at one UTC instant; overlapping ownership fails closed."""
    if wallet_id is None:
        return AccountAttribution(None, "unknown", "wallet_unknown")
    if at is None:
        return AccountAttribution(None, "unknown", "undated")
    _utc(at)
    matches = tuple(
        interval
        for interval in mapping.intervals
        if interval.wallet_id == wallet_id
        and interval.effective_from <= at
        and (interval.effective_until is None or at < interval.effective_until)
    )
    if not matches:
        return AccountAttribution(None, "unknown", "unmapped")
    if len(matches) != 1:
        return AccountAttribution(None, "unknown", "ambiguous")
    match = matches[0]
    return AccountAttribution(match.account_id, match.account_class, "mapped")
