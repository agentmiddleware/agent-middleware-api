"""Exact credit storage shared by request validation and signed services."""

from decimal import Decimal


def credit_amount_fits_storage(amount: Decimal) -> bool:
    """Whether a non-negative Numeric(20, 8) credit amount survives storage.

    SQLite converts the bound Decimal through a float and reconstructs eight
    fractional places, so even some in-scale large values lose precision.
    Keep the same conservative contract on both supported backends; never
    silently round a signed amount.
    """
    return (
        amount.is_finite()
        and Decimal("0") <= amount < Decimal("1000000000000")
        and Decimal(f"{float(amount):.8f}") == amount
    )


def supported_wallet_currency(currency: object) -> str:
    """Return USD, or reject a missing or unsupported currency.

    Wallet balances are one credit unit. The wallet row does not store a
    currency, so a blank code or EUR would still mint credits that spend as
    USD. Only USD is accepted, matching the fiat top-up rail.
    """
    if not isinstance(currency, str):
        raise ValueError("currency is required")
    normalized = currency.strip().upper()
    if normalized != "USD":
        raise ValueError("currency must be USD")
    return "USD"
