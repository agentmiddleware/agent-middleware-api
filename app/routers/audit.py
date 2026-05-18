from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.schemas.audit import AuditEventListResponse, AuditEventResponse
from app.services.audit_log import list_audit_events

router = APIRouter(prefix="/v1/audit", tags=["Control Plane Audit"])


@router.get("/events", response_model=AuditEventListResponse)
async def get_audit_events(
    wallet_id: str | None = Query(None),
    key_id: str | None = Query(None),
    tool: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> AuditEventListResponse:
    auth.require_bootstrap_admin()
    events = await list_audit_events(
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool,
        request_id=request_id,
        limit=limit,
    )
    return AuditEventListResponse(
        events=[AuditEventResponse(**event.__dict__) for event in events],
        total=len(events),
    )
