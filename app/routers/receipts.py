from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import (
    ReceiptResponse,
    ReceiptVerifyRequest,
    ReceiptVerifyResponse,
)
from app.services.receipts import get_receipt_service

router = APIRouter(prefix="/v1/receipts", tags=["Trust Receipts"])


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptResponse:
    receipt = await get_receipt_service().get_receipt(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="receipt_not_found")
    auth.require_wallet_access(receipt.wallet_id)
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
        auth.require_wallet_access(receipt.wallet_id)
    else:
        auth.require_bootstrap_admin()
    return ReceiptVerifyResponse(valid=valid, reason=reason, receipt=receipt)
