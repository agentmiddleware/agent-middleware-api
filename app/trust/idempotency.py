"""Trust-plane facade: idempotent, replay-safe invocation.

Re-exports the canonical idempotency implementation from
:mod:`app.services.idempotency`.
"""

from __future__ import annotations

from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    IdempotencyBegin,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    IdempotencyService,
    get_idempotency_service,
)

__all__ = [
    "GOVERNED_MCP_IDEMPOTENCY_ENDPOINT",
    "IdempotencyBegin",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "IdempotencyReplay",
    "IdempotencyService",
    "get_idempotency_service",
]
