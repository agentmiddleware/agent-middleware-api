"""Trust-plane facade: wallet ledger and spend metering.

This module is a thin re-export only, not a second metering engine. The
canonical implementation lives in :mod:`app.services.agent_money`; every
name here is the same object, and no pricing, charging, or ledger logic may
be added here. Import from here only when expressing the trust-plane
dependency; the behavior under test is always the engine's.
"""

from __future__ import annotations

from app.services.agent_money import (
    DEFAULT_PRICING,
    AgentMoney,
    InsufficientFundsError,
    KYCVerificationRequiredError,
    WalletNotFoundError,
    get_agent_money,
)

__all__ = [
    "DEFAULT_PRICING",
    "AgentMoney",
    "InsufficientFundsError",
    "KYCVerificationRequiredError",
    "WalletNotFoundError",
    "get_agent_money",
]
