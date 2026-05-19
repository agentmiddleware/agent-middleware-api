from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.schemas.audit import (
    AuditEventListResponse,
    AuditEventResponse,
    AuditSummaryResponse,
)
from app.services.audit_log import (
    count_audit_events,
    list_audit_events,
    summarize_audit_events,
)

router = APIRouter(prefix="/v1/audit", tags=["Control Plane Audit"])


def _authorize_audit_events_request(
    *,
    auth: AuthContext,
    wallet_id: str | None,
    key_id: str | None,
    summary: bool,
) -> tuple[str | None, str | None]:
    if auth.is_bootstrap_admin:
        return wallet_id, key_id

    if summary or not wallet_id:
        auth.require_bootstrap_admin()

    auth.require_wallet_access(wallet_id)
    return wallet_id, None


@router.get("/events", response_model=AuditEventListResponse)
async def get_audit_events(
    event: str | None = Query(None),
    wallet_id: str | None = Query(None),
    key_id: str | None = Query(None),
    tool: str | None = Query(None),
    endpoint: str | None = Query(None),
    policy_decision_id: str | None = Query(None),
    request_id: str | None = Query(None),
    ok: bool | None = Query(None),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    summary: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> AuditEventListResponse:
    wallet_id, key_id = _authorize_audit_events_request(
        auth=auth,
        wallet_id=wallet_id,
        key_id=key_id,
        summary=summary,
    )
    events = await list_audit_events(
        event=event,
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool,
        endpoint=endpoint,
        policy_decision_id=policy_decision_id,
        request_id=request_id,
        ok=ok,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    total = await count_audit_events(
        event=event,
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool,
        endpoint=endpoint,
        policy_decision_id=policy_decision_id,
        request_id=request_id,
        ok=ok,
        created_after=created_after,
        created_before=created_before,
    )
    next_offset = offset + len(events) if offset + len(events) < total else None
    response_summary = None
    if summary:
        summary_events = await list_audit_events(
            event=event,
            wallet_id=wallet_id,
            key_id=key_id,
            tool=tool,
            endpoint=endpoint,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            ok=ok,
            created_after=created_after,
            created_before=created_before,
            limit=10_000,
            offset=0,
        )
        by_event: dict[str, int] = {}
        ok_count = 0
        failed_count = 0
        for audit_event in summary_events:
            by_event[audit_event.event] = by_event.get(audit_event.event, 0) + 1
            if audit_event.ok:
                ok_count += 1
            else:
                failed_count += 1
        response_summary = {
            "total": total,
            "ok": ok_count,
            "failed": failed_count,
            "by_event": by_event,
        }
    return AuditEventListResponse(
        events=[AuditEventResponse(**asdict(event)) for event in events],
        total=total,
        limit=limit,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
        summary=response_summary,
    )


@router.get("/summary", response_model=AuditSummaryResponse)
async def get_audit_summary(
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> AuditSummaryResponse:
    auth.require_bootstrap_admin()
    summary = await summarize_audit_events(
        created_after=created_after,
        created_before=created_before,
    )
    return AuditSummaryResponse(**summary)
