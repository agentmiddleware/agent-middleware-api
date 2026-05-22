"""
Admin-only operational endpoints. All require a bootstrap/admin API key.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..audit.lightweight import get_recent_audit, record_audit
from ..core.auth import AuthContext, get_auth_context

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/audit", summary="Export recent audit events (admin only)")
async def export_audit(
    auth: AuthContext = Depends(get_auth_context),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    event: str | None = Query(None, description="Filter by event-name prefix"),
) -> dict[str, Any]:
    """Return recent structured audit events from the in-memory ring buffer.

    Best-effort recent history; durable audit comes from shipping the audit
    JSON log lines to a collector.
    """
    auth.require_bootstrap_admin()
    events = get_recent_audit(limit=limit, event_prefix=event)
    record_audit(
        "admin.audit_export",
        source=auth.source,
        key_id=auth.key_id,
        returned=len(events),
        event_filter=event,
    )
    return {"count": len(events), "events": events}
