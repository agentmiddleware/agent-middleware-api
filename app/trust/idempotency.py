"""Trust-plane facade: idempotent, replay-safe invocation.

Re-exports the canonical idempotency implementation from
:mod:`app.services.idempotency`.
"""

from __future__ import annotations

from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    IdempotencyBegin,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    IdempotencyService,
    InvalidIdempotencyKeyError,
    get_idempotency_service,
    invalid_idempotency_key_detail,
    resolve_client_idempotency_key,
    validate_idempotency_key,
)

__all__ = [
    "GOVERNED_MCP_IDEMPOTENCY_ENDPOINT",
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "IdempotencyBegin",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "IdempotencyReplay",
    "IdempotencyService",
    "InvalidIdempotencyKeyError",
    "get_idempotency_service",
    "invalid_idempotency_key_detail",
    "resolve_client_idempotency_key",
    "validate_idempotency_key",
]
