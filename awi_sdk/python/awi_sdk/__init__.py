"""
AWI Python SDK — Phase 8
=========================
Lightweight Python client for interacting with AWI-enabled services.

Source-only alpha: not published to PyPI. From a repository checkout,
install the local distribution with ``python -m pip install -e
awi_sdk/python`` (see ``awi_sdk/python/README.md`` and
``awi_sdk/python/pyproject.toml``).
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
