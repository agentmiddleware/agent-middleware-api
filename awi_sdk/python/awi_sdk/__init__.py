"""
AWI Python SDK — Phase 8
=========================
Lightweight Python client for interacting with AWI-enabled services.

Not published to PyPI and not pip-installable from this repository
(no pyproject.toml). Add awi_sdk/python to PYTHONPATH from a checkout.
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
