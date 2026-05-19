from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.audit import AuditEventListResponse, AuditEventResponse
from app.schemas.trust import PermitListResponse, ReceiptListResponse
from app.services.audit_log import count_audit_events, list_audit_events
from app.services.permits import get_permit_service
from app.services.receipts import get_receipt_service

router = APIRouter(prefix="/v1/me", tags=["Agent Self Inspection"])


def _require_wallet_key(auth: AuthContext) -> tuple[str, str | None]:
    if auth.is_bootstrap_admin or not auth.wallet_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "wallet_key_required",
                "message": "This endpoint requires a DB-backed wallet API key.",
            },
        )
    return auth.wallet_id, auth.key_id


@router.get("/permits", response_model=PermitListResponse)
async def list_my_permits(
    status: str | None = Query(None),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    expires_after: datetime | None = Query(None),
    expires_before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> PermitListResponse:
    wallet_id, key_id = _require_wallet_key(auth)
    permits, total = await get_permit_service().list_permits(
        wallet_id=wallet_id,
        status=status,
        subject_key_id=key_id,
        created_after=created_after,
        created_before=created_before,
        expires_after=expires_after,
        expires_before=expires_before,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(permits) if offset + len(permits) < total else None
    return PermitListResponse(
        permits=permits,
        total=total,
        limit=limit,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
    )


@router.get("/receipts", response_model=ReceiptListResponse)
async def list_my_receipts(
    permit_id: str | None = Query(None),
    tool: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptListResponse:
    wallet_id, _ = _require_wallet_key(auth)
    receipts, total = await get_receipt_service().list_receipts(
        permit_id=permit_id,
        wallet_id=wallet_id,
        tool=tool,
        outcome=outcome,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(receipts) if offset + len(receipts) < total else None
    return ReceiptListResponse(
        receipts=receipts,
        total=total,
        limit=limit,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
    )


@router.get("/audit/events", response_model=AuditEventListResponse)
async def list_my_audit_events(
    event: str | None = Query(None),
    tool: str | None = Query(None),
    endpoint: str | None = Query(None),
    policy_decision_id: str | None = Query(None),
    request_id: str | None = Query(None),
    ok: bool | None = Query(None),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> AuditEventListResponse:
    wallet_id, key_id = _require_wallet_key(auth)
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
    return AuditEventListResponse(
        events=[AuditEventResponse(**asdict(event)) for event in events],
        total=total,
        limit=limit,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
    )
