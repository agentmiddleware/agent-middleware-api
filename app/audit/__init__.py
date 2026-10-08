"""Structured operational-log helpers (stdout telemetry, not audit evidence).

For the authoritative tamper-evident record, see
``app.services.audit_log`` and ``app.services.audit_chain``."""

from .lightweight import record_audit

__all__ = ["record_audit"]
