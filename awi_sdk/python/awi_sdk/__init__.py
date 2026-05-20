"""
AWI Python SDK — Phase 8
=========================
Lightweight Python client for interacting with AWI-enabled services.

pip install agent-middleware-awi
"""

from .client import AWIClient, AWIClientConfig
from .models import (
    AWIActionDefinition,
    AWIActionRiskLevel,
    AWIActionStatus,
    AWIActionTier,
    AWIRepresentationType,
    AWIStandardAction,
    AWIExecutionResponse,
    AWISession,
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
]

__version__ = "0.1.0"
