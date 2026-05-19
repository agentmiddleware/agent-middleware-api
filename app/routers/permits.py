from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import (
    PermitCreateRequest,
    PermitResponse,
    PermitVerifyRequest,
    PermitVerifyResponse,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    get_idempotency_service,
)
from app.services.permits import PermitError, get_permit_service, permit_model_to_response

router = APIRouter(prefix="/v1/permits", tags=["Trust Permits"])


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
    except IdempotencyConflictError as exc:
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
    return PermitVerifyResponse(
        valid=validation.allowed,
        reason=validation.reason,
        permit=permit_model_to_response(validation.permit) if validation.permit else None,
    )
