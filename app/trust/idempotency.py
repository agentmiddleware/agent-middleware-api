"""Trust-plane facade: idempotent, replay-safe invocation.

Re-exports the canonical idempotency implementation from
:mod:`app.services.idempotency`.
"""

from __future__ import annotations

from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    IdempotencyService,
    get_idempotency_service,
)

__all__ = [
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "IdempotencyReplay",
    "IdempotencyService",
    "get_idempotency_service",
]
