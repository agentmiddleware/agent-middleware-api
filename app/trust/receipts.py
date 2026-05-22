"""Trust-plane facade: signed action receipts.

Re-exports the canonical receipt implementation from
:mod:`app.services.receipts`.
"""

from __future__ import annotations

from app.services.receipts import (
    ReceiptError,
    ReceiptService,
    get_receipt_service,
)

__all__ = [
    "ReceiptError",
    "ReceiptService",
    "get_receipt_service",
]
