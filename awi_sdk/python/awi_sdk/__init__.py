"""
AWI Python SDK — Phase 8
=========================
Lightweight Python client for interacting with AWI-enabled services.

pip install agent-middleware-awi
"""

from .client import AWIClient, AWIClientConfig
from .models import (
    AWIStandardAction,
    AWIRepresentationType,
    AWISession,
    AWIExecutionResponse,
)

__all__ = [
    "AWIClient",
    "AWIClientConfig",
    "AWIStandardAction",
    "AWIRepresentationType",
    "AWISession",
    "AWIExecutionResponse",
]

__version__ = "0.1.0"
