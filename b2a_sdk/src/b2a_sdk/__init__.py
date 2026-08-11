"""Python client for governed Agent Middleware tool calls."""

from .client import AgentMiddlewareClient, B2AClient
from .decorators import billable, combined, monitored
from .edge_client import B2AEdgeClient
from .errors import (
    AgentMiddlewareError,
    APIError,
    AuthenticationError,
    AuthorizationError,
    DeliveryUncertainError,
    IdempotencyConflictError,
    InsufficientFundsError,
    PermitDeniedError,
    TransportError,
)
from .models import (
    EvidenceBundle,
    InvocationResult,
    Permit,
    PermitRequest,
    Receipt,
    ReceiptVerification,
    ToolDefinition,
)
from .receipt_verifier import (
    VerificationError,
    VerificationResult,
    VerificationStatus,
    key_set_from_document,
    verify_bundle,
)

__version__ = "0.4.0"
__all__ = [
    "APIError",
    "AgentMiddlewareClient",
    "AgentMiddlewareError",
    "AuthenticationError",
    "AuthorizationError",
    "B2AClient",
    "B2AEdgeClient",
    "DeliveryUncertainError",
    "EvidenceBundle",
    "IdempotencyConflictError",
    "InsufficientFundsError",
    "InvocationResult",
    "Permit",
    "PermitDeniedError",
    "PermitRequest",
    "Receipt",
    "ReceiptVerification",
    "ToolDefinition",
    "TransportError",
    "VerificationError",
    "VerificationResult",
    "VerificationStatus",
    "billable",
    "combined",
    "monitored",
    "key_set_from_document",
    "verify_bundle",
]
