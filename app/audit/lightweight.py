"""
Minimal structured audit log.

Emits one JSON object per line on the audit logger (for log shipping) and keeps
a bounded in-memory ring buffer of recent events so an admin can inspect them
via the audit export endpoint without a full audit service yet.

The ring buffer is process-local and best-effort (recent events only). Durable
audit history comes from shipping the JSON log lines to a collector.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any
import json
import logging

logger = logging.getLogger("agent_middleware.audit")

_MAX_RECENT = 1000
_recent: deque[dict[str, Any]] = deque(maxlen=_MAX_RECENT)
_lock = threading.Lock()


def record_audit(event: str, **fields: Any) -> None:
    """Emit one JSON object on the audit logger and retain it in the ring buffer."""
    payload: dict[str, Any] = {
        "event": event,
        "ts": time.time(),
        **fields,
    }
    with _lock:
        _recent.append(payload)
    logger.info("%s", json.dumps(payload, default=str))


def get_recent_audit(
    limit: int = 100, event_prefix: str | None = None
) -> list[dict[str, Any]]:
    """Return the most recent audit events (newest last), optionally filtered by
    an event-name prefix."""
    with _lock:
        events = list(_recent)
    if event_prefix:
        events = [e for e in events if str(e.get("event", "")).startswith(event_prefix)]
    if limit > 0:
        events = events[-limit:]
    return events
