"""
Minimal structured operational log (stdout via logging).

Use for MCP invocations and other security-sensitive actions. Downstream can
ship JSON logs to a collector without a full audit service yet.

This log is operational telemetry only: entries are unsigned and unchained.
The authoritative tamper-evident record is the per-wallet hash-chained and
signed chain written by ``app.services.audit_log.record_audit_event`` and
checked by ``POST /v1/audit/verify-chain``. Do not present stdout entries as
audit evidence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("agent_middleware.audit")


def record_audit(event: str, **fields: Any) -> None:
    """Emit one JSON object per line on the audit logger (level INFO)."""
    payload: dict[str, Any] = {"event": event, **fields}
    logger.info("%s", json.dumps(payload, default=str))
