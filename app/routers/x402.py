from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import AuthContext, get_auth_context
from app.core.time import utc_now
from app.services.x402_engine import X402_TOOL_NAME, X402Error, get_x402_handler
from app.trust import (
    IdempotencyBegin,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PermitError,
    get_idempotency_service,
    get_receipt_service,
    record_audit_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/x402", tags=["X402 Settlement"])

_SETTLE_ENDPOINT = "/v1/x402/settle"

# An in-progress settle record idle past this threshold is treated as a
# crashed attempt and recovered (see _recover_stale_settle_record); mirrors
# the repo's 300s staleness standard (the ACP bridge's stale-intent recovery
# and the governed-MCP reconciliation sweep). Safety invariant, not a
# heuristic: a live settle makes no outbound network call at all — permit
# reservation, Ed25519 attestation signing, shadow-ledger metering, and the
# receipt write are all local DB/CPU work — so its wall-clock upper bound
# sits far below this threshold and a record older than it cannot belong to
# a live attempt. Backstop if that ever regresses: abandon() refuses
# completed or charged records, and the receipts table's
# idempotency_record_id link means a receipted record is never abandoned
# here (it takes the settled-unrecoverable branch instead).
_SETTLE_STALE_SECONDS = 300


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
    # Payer wallet's on-chain address. Required for EVM networks: the
    # facilitator attestation signs the exact EIP-712 message, so `from`
    # must be the real payer, not a blank the wallet fills in afterwards.
    payer: str | None = None


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


async def _recover_stale_settle_record(
    request: X402SettleRequest,
    *,
    idempotency_key: str,
    key_id: str | None,
    in_progress: IdempotencyInProgressError,
) -> IdempotencyBegin:
    """Recover a settle Idempotency-Key wedged by a crashed attempt.

    begin_with_record raising IdempotencyInProgressError can mean a live
    concurrent settle — or the wreckage of a process that died between
    handler.settle and idem.complete. Nothing else repairs this endpoint's
    records (reconcile_stuck_records covers only governed MCP identities,
    and no ledger_entry_id checkpoint exists here), so without this branch a
    crashed attempt wedges the key forever: every retry 409s. Port of the
    ACP bridge's stale-intent recovery, resolved by crash shape once the
    record is idle past _SETTLE_STALE_SECONDS:

    - no receipt references the record: the attempt died before the durable
      settlement record was written, and the engine's compensation (budget
      release, no receipt, no live shadow session) either ran or is covered
      by permit expiry. Record the recovery on the audit chain, abandon the
      record (abandon refuses completed/charged ones), and re-run begin so
      the retry proceeds fresh.
    - a receipt DOES reference the record: the settlement happened and is
      durable, but the original X402SettleResponse cannot be rebuilt from
      what is persisted — receipts store only request/response payload
      *hashes*, and the response's authorization dict, Ed25519 attestation
      signature, and shadow session/charge ids live nowhere reconstructable
      byte-for-byte (re-signing the attestation is only bit-stable while
      the signing key is unrotated, and the shadow ids are in unsigned
      audit metadata, not the receipt). Completing the record with guessed
      or partial fields would forge a replay, so this returns a DISTINCT
      typed 409 — x402_settled_unrecoverable_replay — telling the caller
      the key settled durably (budget consumed, receipt verifiable via
      /v1/receipts) but the verbatim response is unrecoverable. Contract
      asserted by test_x402_stale_receipted_record_is_settled_unrecoverable.
    """
    idem = get_idempotency_service()
    record = await idem.get_record(
        wallet_id=request.wallet_id,
        endpoint=_SETTLE_ENDPOINT,
        idempotency_key=idempotency_key,
    )
    stale = (
        record is not None
        and record.response_json is None
        and not record.ledger_entry_id
        and record.created_at
        < utc_now() - timedelta(seconds=_SETTLE_STALE_SECONDS)
    )
    if not stale:
        # Possibly a live concurrent attempt: refuse, exactly as before.
        raise HTTPException(status_code=409, detail=in_progress.args[0])
    assert record is not None
    receipt = await get_receipt_service().get_receipt_by_idempotency_record_id(
        record.record_id
    )
    if receipt is not None:
        raise HTTPException(
            status_code=409, detail="x402_settled_unrecoverable_replay"
        )
    # Mark the recovery on the audit chain BEFORE abandoning (mirrors
    # acp_intent_recovered): the re-run may legitimately leave a second
    # reservation trail for this key, and this event lets an operator read
    # that shape as crash recovery rather than a defect. Best-effort —
    # recovering a wedged key must not fail on evidence bookkeeping.
    try:
        await record_audit_event(
            event="x402_settle_recovered",
            wallet_id=request.wallet_id,
            tool=X402_TOOL_NAME,
            endpoint=_SETTLE_ENDPOINT,
            key_id=key_id,
            request_id=idempotency_key[:100],
            ok=True,
            metadata={
                "idempotency_key": idempotency_key,
                "permit_id": request.permit_id,
                "abandoned_record_id": record.record_id,
            },
        )
    except Exception:
        logger.exception(
            "Failed to record x402_settle_recovered evidence for key %s",
            idempotency_key,
        )
    await idem.abandon(
        wallet_id=request.wallet_id,
        endpoint=_SETTLE_ENDPOINT,
        idempotency_key=idempotency_key,
    )
    try:
        return await idem.begin_with_record(
            wallet_id=request.wallet_id,
            endpoint=_SETTLE_ENDPOINT,
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
        )
    except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
        raise HTTPException(status_code=409, detail=exc.args[0])


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
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.args[0])
    except IdempotencyInProgressError as exc:
        # A fresh in-progress record is still a hard 409; a stale one is a
        # crashed attempt and is recovered (or reported as settled-but-
        # unrecoverable) — see _recover_stale_settle_record.
        begun = await _recover_stale_settle_record(
            request,
            idempotency_key=idempotency_key,
            key_id=auth.key_id,
            in_progress=exc,
        )
    if begun.replay and begun.replay.response_json:
        return X402SettleResponse(**begun.replay.response_json)

    try:
        settlement = await handler.settle(
            permit_id=request.permit_id,
            wallet_id=request.wallet_id,
            key_id=auth.key_id,
            requirement=requirement,
            idempotency_key=idempotency_key,
            payer=request.payer,
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
