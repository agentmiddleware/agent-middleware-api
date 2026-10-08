"""
AWI Python SDK — Phase 8
=========================
Lightweight Python client for interacting with AWI-enabled services.

Install from this checkout (not published to PyPI)::

    python -m pip install ./awi_sdk/python

Proof surface note: the ``/v1/awi/*`` routes this client calls are frozen
proof surfaces, unmounted in production-like deployments
(``ENABLE_PROOF_SURFACES=false``). Point the client at a server started
with proof surfaces enabled. See ``docs/PROOF_SURFACES.md``.
"""

from .client import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    RETRYABLE_STATUS_CODES,
    AWIClient,
    AWIClientConfig,
)
from .errors import (
    AuthenticationError,
    AuthorizationError,
    AWIAPIError,
    AWIError,
    IdempotencyConflictError,
    PermitDeniedError,
)
from .models import (
    AWIActionDefinition,
    AWIActionRiskLevel,
    AWIActionStatus,
    AWIActionTier,
    AWIExecutionResponse,
    AWIRepresentationType,
    AWISession,
    AWIStandardAction,
)

__all__ = [
    "AWIClient",
    "AWIClientConfig",
    "AWIActionDefinition",
    "AWIActionRiskLevel",
    "AWIActionStatus",
    "AWIActionTier",
    "AWIStandardAction",
    "AWIRepresentationType",
    "AWISession",
    "AWIExecutionResponse",
    "AWIError",
    "AWIAPIError",
    "AuthenticationError",
    "AuthorizationError",
    "PermitDeniedError",
    "IdempotencyConflictError",
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "RETRYABLE_STATUS_CODES",
]

__version__ = "0.1.0"
