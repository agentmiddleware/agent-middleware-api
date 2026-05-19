from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import (
    ReceiptListResponse,
    ReceiptResponse,
    ReceiptVerifyRequest,
    ReceiptVerifyResponse,
)
from app.services.permits import get_permit_service
from app.services.receipts import get_receipt_service

router = APIRouter(prefix="/v1/receipts", tags=["Trust Receipts"])


async def _authorize_receipt_list(
    *,
    auth: AuthContext,
    wallet_id: str | None,
    permit_id: str | None,
) -> None:
    if permit_id:
        permit = await get_permit_service().get_permit(permit_id)
        if not permit:
            raise HTTPException(status_code=404, detail="permit_not_found")
        if wallet_id and wallet_id not in {
            permit.issuer_wallet_id,
            permit.subject_wallet_id,
        }:
            auth.require_bootstrap_admin()
            return
        if auth.is_bootstrap_admin:
            return
        if auth.wallet_id in {permit.issuer_wallet_id, permit.subject_wallet_id}:
            return
    if wallet_id:
        auth.require_wallet_access(wallet_id)
        return
    auth.require_bootstrap_admin()


async def _authorize_receipt_access(
    *,
    auth: AuthContext,
    receipt: ReceiptResponse,
) -> None:
    if auth.is_bootstrap_admin:
        return
    if auth.wallet_id == receipt.wallet_id:
        return
    permit = await get_permit_service().get_permit(receipt.permit_id)
    if permit and auth.wallet_id in {permit.issuer_wallet_id, permit.subject_wallet_id}:
        return
    auth.require_wallet_access(receipt.wallet_id)


@router.get("", response_model=ReceiptListResponse)
async def list_receipts(
    permit_id: str | None = Query(None),
    wallet_id: str | None = Query(None),
    tool: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptListResponse:
    await _authorize_receipt_list(auth=auth, wallet_id=wallet_id, permit_id=permit_id)
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


@router.get("/permit/{permit_id}", response_model=ReceiptListResponse)
async def list_receipts_for_permit(
    permit_id: str,
    wallet_id: str | None = Query(None),
    tool: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptListResponse:
    await _authorize_receipt_list(auth=auth, wallet_id=wallet_id, permit_id=permit_id)
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


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptResponse:
    receipt = await get_receipt_service().get_receipt(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="receipt_not_found")
    await _authorize_receipt_access(auth=auth, receipt=receipt)
    return receipt


@router.post("/verify", response_model=ReceiptVerifyResponse)
async def verify_receipt(
    request: ReceiptVerifyRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptVerifyResponse:
    valid, reason, receipt = await get_receipt_service().verify_receipt(
        request.receipt_id
    )
    if receipt:
        await _authorize_receipt_access(auth=auth, receipt=receipt)
    else:
        auth.require_bootstrap_admin()
    return ReceiptVerifyResponse(valid=valid, reason=reason, receipt=receipt)
