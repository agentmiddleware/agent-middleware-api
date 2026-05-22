"""Trust-plane facade: signed, bounded authority (permits).

Re-exports the canonical permit implementation from :mod:`app.services.permits`.
"""

from __future__ import annotations

from app.services.permits import (
    PermitError,
    PermitService,
    PermitValidation,
    get_permit_service,
    permit_model_to_response,
)

__all__ = [
    "PermitError",
    "PermitService",
    "PermitValidation",
    "get_permit_service",
    "permit_model_to_response",
]
