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
    AgentMoney,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PermitError,
    get_agent_money,
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
    elif auth.wallet_id:
        # An unscoped list is an operator view. A wallet key asking for it means
        # "my permits", so scope it to the caller rather than refusing: the
        # data was already readable at /v1/me/permits, and needing an admin key
        # to see your own permits by issuer/expiry filters was the gate in the
        # wrong place.
        wallet_id = auth.wallet_id
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
    money: AgentMoney = Depends(get_agent_money),
) -> PermitResponse:
    auth.require_wallet_access(request.issuer_wallet_id)
    # Authorizing only the issuer let any wallet holder mint a signed permit
    # against an arbitrary victim wallet (charged when used, listed in the
    # victim's own permits) and probe foreign balances via the creation error.
    # The subject is the wallet the permit encumbers, so the issuer must have
    # authority over it: itself or a wallet it funds in the sponsor -> agent ->
    # child hierarchy. Bootstrap admins are unrestricted.
    if not auth.is_bootstrap_admin and not await money.is_wallet_or_descendant(
        request.subject_wallet_id, request.issuer_wallet_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "subject_wallet_access_denied",
                "message": (
                    "The permit subject wallet must be the issuer wallet or a "
                    "wallet it funds."
                ),
            },
        )
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
        permit = await get_permit_service().create_permit(request, subject_key_id=auth.key_id)
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
    # ``verify`` answers "would this exact action be admitted?", so it needs
    # the action: which wallet acts, and which tool it calls. Evaluated against
    # an empty string, an omitted field produces a verdict about a call nobody
    # meant to make — a binding reason that reads as "this permit is not yours"
    # to the permit's own subject, or, for a permit with an empty allowlist and
    # a matching empty-tool scope, an outright ``valid: true``. Neither is an
    # answer, so name the missing context instead of returning one.
    #
    # Lifecycle reasons are exempt: a permit that is expired or no longer
    # active is refused whatever action you name, so that verdict is real even
    # from an incomplete request. ``permit_not_found`` (no permit at all) is
    # likewise left to speak for itself below.
    missing = [
        field
        for field, value in (
            ("wallet_id", request.wallet_id),
            ("tool", request.tool),
        )
        if not value
    ]
    lifecycle_denial = validation.reason == "permit_expired" or (
        permit is not None and permit.status != "active"
    )
    if missing and permit is not None and not lifecycle_denial:
        return PermitVerifyResponse(
            valid=False,
            reason="permit_verify_context_missing",
            details={"missing": missing},
            permit=permit_model_to_response(permit),
        )
    return PermitVerifyResponse(
        valid=validation.allowed,
        reason=validation.reason,
        details=validation.details,
        permit=permit_model_to_response(permit) if permit else None,
    )
