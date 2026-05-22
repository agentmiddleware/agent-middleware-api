from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import (
    PermitCreateRequest,
    PermitListResponse,
    PermitResponse,
    PermitVerifyRequest,
    PermitVerifyResponse,
    ReceiptListResponse,
)
from app.trust import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PermitError,
    get_idempotency_service,
    get_permit_service,
    get_receipt_service,
    permit_model_to_response,
)

router = APIRouter(prefix="/v1/permits", tags=["Trust Permits"])


def _authorize_permit_inspection(
    *,
    auth: AuthContext,
    issuer_wallet_id: str,
    subject_wallet_id: str,
) -> None:
    if auth.is_bootstrap_admin:
        return
    if auth.wallet_id in {issuer_wallet_id, subject_wallet_id}:
        return
    auth.require_bootstrap_admin()


@router.get("", response_model=PermitListResponse)
async def list_permits(
    wallet_id: str | None = Query(None),
    status: str | None = Query(None),
    subject_key_id: str | None = Query(None),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    expires_after: datetime | None = Query(None),
    expires_before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> PermitListResponse:
    if wallet_id:
        auth.require_wallet_access(wallet_id)
    else:
        auth.require_bootstrap_admin()

    permits, total = await get_permit_service().list_permits(
        wallet_id=wallet_id,
        status=status,
        subject_key_id=subject_key_id,
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


@router.post("", response_model=PermitResponse, status_code=status.HTTP_201_CREATED)
async def create_permit(
    request: PermitCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_auth_context),
) -> PermitResponse:
    auth.require_wallet_access(request.issuer_wallet_id)
    idem = get_idempotency_service()
    try:
        replay = await idem.begin(
            wallet_id=request.issuer_wallet_id,
            endpoint="/v1/permits",
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
        )
    except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
        raise HTTPException(status_code=409, detail=exc.args[0])
    if replay and replay.response_json:
        return PermitResponse(**replay.response_json)

    try:
        permit = await get_permit_service().create_permit(request)
    except PermitError as exc:
        raise HTTPException(status_code=400, detail=exc.reason)
    await idem.complete(
        wallet_id=request.issuer_wallet_id,
        endpoint="/v1/permits",
        idempotency_key=idempotency_key,
        response_reference=permit.permit_id,
        response_json=permit.model_dump(mode="json"),
        status_code=201,
    )
    return permit


@router.get("/{permit_id}", response_model=PermitResponse)
async def get_permit(
    permit_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> PermitResponse:
    permit = await get_permit_service().get_permit(permit_id)
    if not permit:
        raise HTTPException(status_code=404, detail="permit_not_found")
    _authorize_permit_inspection(
        auth=auth,
        issuer_wallet_id=permit.issuer_wallet_id,
        subject_wallet_id=permit.subject_wallet_id,
    )
    return permit


@router.get("/{permit_id}/receipts", response_model=ReceiptListResponse)
async def list_permit_receipts(
    permit_id: str,
    tool: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptListResponse:
    permit = await get_permit_service().get_permit(permit_id)
    if not permit:
        raise HTTPException(status_code=404, detail="permit_not_found")
    _authorize_permit_inspection(
        auth=auth,
        issuer_wallet_id=permit.issuer_wallet_id,
        subject_wallet_id=permit.subject_wallet_id,
    )
    receipts, total = await get_receipt_service().list_receipts(
        permit_id=permit_id,
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


@router.post("/{permit_id}/revoke", response_model=PermitResponse)
async def revoke_permit(
    permit_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> PermitResponse:
    service = get_permit_service()
    existing = await service.get_permit(permit_id)
    if not existing:
        raise HTTPException(status_code=404, detail="permit_not_found")
    auth.require_wallet_access(existing.issuer_wallet_id)
    try:
        permit = await service.revoke_permit(permit_id)
    except PermitError as exc:
        raise HTTPException(status_code=404, detail=exc.reason)
    return permit


@router.post("/verify", response_model=PermitVerifyResponse)
async def verify_permit(
    request: PermitVerifyRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> PermitVerifyResponse:
    if request.wallet_id:
        auth.require_wallet_access(request.wallet_id)
    estimated = request.estimated_credits or Decimal("0")
    validation = await get_permit_service().validate_for_action(
        permit_id=request.permit_id,
        wallet_id=request.wallet_id or "",
        tool_name=request.tool or "",
        estimated_credits=estimated,
        key_id=auth.key_id,
    )
    permit = validation.permit
    # The validation result carries the full permit (issuer/subject wallets,
    # scopes, budget). Only return it to a caller authorized for that permit —
    # otherwise any authenticated agent could read any permit by id.
    if permit is not None and not auth.is_bootstrap_admin:
        if auth.wallet_id not in {permit.issuer_wallet_id, permit.subject_wallet_id}:
            raise HTTPException(status_code=403, detail="permit_access_denied")
    return PermitVerifyResponse(
        valid=validation.allowed,
        reason=validation.reason,
        permit=permit_model_to_response(permit) if permit else None,
    )
