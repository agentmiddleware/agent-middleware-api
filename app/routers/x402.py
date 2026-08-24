from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import AuthContext, get_auth_context
from app.services.x402_engine import X402Error, get_x402_handler
from app.trust import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PermitError,
    get_idempotency_service,
)

router = APIRouter(prefix="/v1/x402", tags=["X402 Settlement"])

_SETTLE_ENDPOINT = "/v1/x402/settle"


# Response/request models live in the router module: the x402 surface is small
# and dormant, so it keeps its schemas local rather than growing app/schemas.


class X402ParseRequest(BaseModel):
    """An upstream HTTP response's status and headers, as observed."""

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)


class X402RequirementResponse(BaseModel):
    amount_usd: str
    pay_to: str
    network: str
    asset: str


class X402SettleRequest(BaseModel):
    permit_id: str
    wallet_id: str
    amount: Decimal
    pay_to: str
    network: str
    asset: str = "USDC"


class X402AttestationResponse(BaseModel):
    """Ed25519 facilitator attestation — trust-plane evidence, not on-chain."""

    alg: str
    signature: str
    key_id: str
    payload_hash: str


class X402SettleResponse(BaseModel):
    permit_id: str
    wallet_id: str
    network: str
    pay_to: str
    asset: str
    amount_usd: str
    # Exact decimal string; the permit budget was reserved for this amount.
    credits: str
    # What the payer wallet must sign (EIP-712 typed data or Solana message).
    authorization: dict[str, Any]
    attestation: X402AttestationResponse
    receipt_id: str
    shadow_session_id: str
    shadow_charge_id: str | None = None
    audit_event_id: str | None = None


@router.post("/parse", response_model=X402RequirementResponse)
async def parse_payment_required(
    request: X402ParseRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> X402RequirementResponse:
    """Strictly parse an observed HTTP 402 into a payment requirement."""
    del auth  # authenticated-only surface; parsing itself is tenant-neutral
    try:
        requirement = get_x402_handler().parse_402(
            request.status_code, request.headers
        )
    except X402Error as exc:
        raise HTTPException(status_code=400, detail=exc.reason)
    return X402RequirementResponse(
        amount_usd=str(requirement.amount_usd),
        pay_to=requirement.pay_to,
        network=requirement.network,
        asset=requirement.asset,
    )


@router.post("/settle", response_model=X402SettleResponse)
async def settle_payment_required(
    request: X402SettleRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_auth_context),
) -> X402SettleResponse:
    """Authorize a 402 demand against a permit and record the settlement.

    Facilitation only: budget is reserved on the permit, the settlement is
    metered in the shadow ledger, and a signed receipt is emitted — no real
    ledger entry is written and no credits are minted (settlement freeze,
    docs/settlement-rails.md).
    """
    handler = get_x402_handler()
    try:
        requirement = handler.build_requirement(
            amount=request.amount,
            pay_to=request.pay_to,
            network=request.network,
            asset=request.asset,
        )
    except X402Error as exc:
        raise HTTPException(status_code=400, detail=exc.reason)

    auth.require_wallet_access(request.wallet_id)

    idem = get_idempotency_service()
    try:
        begun = await idem.begin_with_record(
            wallet_id=request.wallet_id,
            endpoint=_SETTLE_ENDPOINT,
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
        )
    except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
        raise HTTPException(status_code=409, detail=exc.args[0])
    if begun.replay and begun.replay.response_json:
        return X402SettleResponse(**begun.replay.response_json)

    try:
        settlement = await handler.settle(
            permit_id=request.permit_id,
            wallet_id=request.wallet_id,
            key_id=auth.key_id,
            requirement=requirement,
            idempotency_key=idempotency_key,
            idempotency_record_id=begun.record_id,
        )
    except X402Error as exc:
        # Every settle failure is fully compensated (budget released, no
        # receipt), so release the key for retry rather than freezing a
        # transient denial into a permanent replay.
        await idem.abandon(
            wallet_id=request.wallet_id,
            endpoint=_SETTLE_ENDPOINT,
            idempotency_key=idempotency_key,
        )
        status_code = 404 if exc.reason == "permit_not_found" else 400
        raise HTTPException(status_code=status_code, detail=exc.reason)
    except PermitError as exc:
        await idem.abandon(
            wallet_id=request.wallet_id,
            endpoint=_SETTLE_ENDPOINT,
            idempotency_key=idempotency_key,
        )
        # permit_write_contended is transient: 503 so the caller retries the
        # same key (matching the AWI governance mapping).
        status_code = 503 if exc.reason == "permit_write_contended" else 400
        raise HTTPException(status_code=status_code, detail=exc.reason)

    response = X402SettleResponse(
        permit_id=settlement.permit_id,
        wallet_id=settlement.wallet_id,
        network=requirement.network,
        pay_to=requirement.pay_to,
        asset=requirement.asset,
        amount_usd=str(requirement.amount_usd),
        credits=str(settlement.credits),
        authorization=settlement.authorization,
        attestation=X402AttestationResponse(
            alg="Ed25519",
            signature=settlement.attestation_signature,
            key_id=settlement.attestation_key_id,
            payload_hash=settlement.attestation_payload_hash,
        ),
        receipt_id=settlement.receipt_id,
        shadow_session_id=settlement.shadow_session_id,
        shadow_charge_id=settlement.shadow_charge_id,
        audit_event_id=settlement.audit_event_id,
    )
    await idem.complete(
        wallet_id=request.wallet_id,
        endpoint=_SETTLE_ENDPOINT,
        idempotency_key=idempotency_key,
        response_reference=settlement.receipt_id,
        response_json=response.model_dump(mode="json"),
        status_code=200,
    )
    return response
