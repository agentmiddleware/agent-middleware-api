"""Shared bounds for permit, billing, and key request bodies.

These checks exist so a value the schema accepts cannot later overflow a
database column, mint a boolean as money, or blow the stack while walking
nested JSON.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.credits import credit_amount_fits_storage

# Deep enough for real argument trees, shallow enough that a recursive walk
# of the same value cannot exhaust the interpreter stack.
MAX_JSON_DEPTH = 32
# api_keys.max_uses is a signed 32-bit integer column.
MAX_API_KEY_USES = 2_147_483_647
# timedelta(days=10_000_000) overflows. Two million days from 2026 still
# lands well before year 9999.
MAX_API_KEY_EXPIRES_IN_DAYS = 2_000_000
REVOKE_REASON_MAX_LENGTH = 255
EMERGENCY_REVOKE_REASON_PREFIX = "EMERGENCY: "
EMERGENCY_REASON_MAX_LENGTH = REVOKE_REASON_MAX_LENGTH - len(
    EMERGENCY_REVOKE_REASON_PREFIX
)
WALLET_ID_MAX_LENGTH = 50
TOOL_NAME_MAX_LENGTH = 128


def reject_nul(value: str) -> str:
    """Postgres rejects a NUL byte in every string column."""
    if "\x00" in value:
        raise ValueError("nul_not_allowed")
    return value


def reject_nul_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return reject_nul(value)


def reject_bool_number(value: Any) -> Any:
    """bool is an int subclass, so lax mode would turn true into 1."""
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    return value


def require_storable_amount(value: float | None) -> float | None:
    """Keep amounts that survive Numeric(20, 8) float round-trip storage."""
    if value is None:
        return None
    amount = Decimal(str(value))
    if not credit_amount_fits_storage(amount):
        raise ValueError("amount_not_storable")
    return value


def reject_deep_json(value: Any, *, max_depth: int = MAX_JSON_DEPTH) -> Any:
    """Refuse a nested list or object past max_depth.

    The walk uses an explicit stack. A hostile payload must not be able to
    crash the check that is supposed to reject it.
    """
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            if depth > max_depth:
                raise ValueError("json_too_deep")
            child_depth = depth + 1
            for child in node.values():
                stack.append((child, child_depth))
        elif isinstance(node, list):
            if depth > max_depth:
                raise ValueError("json_too_deep")
            child_depth = depth + 1
            for child in node:
                stack.append((child, child_depth))
    return value
