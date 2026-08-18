"""
Governed AWI HTTP actions — close the HTTP bypass of the MCP trust spine.

High-risk ``/v1/awi/*`` mutating routes require the same permit + idempotency
headers as governed MCP tools, then meter and receipt the attempt.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import Header, HTTPException, status

from app.core.auth import AuthContext
from app.db.models import PermitModel
from app.schemas.billing import ServiceCategory
from app.services.agent_money import AgentMoney, get_agent_money
from app.services.governed_metering import (
    ChargeCreditMismatchError,
    aligned_credits_charged,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    get_idempotency_service,
)
from app.services.permits import get_permit_service
from app.services.receipts import get_receipt_service

logger = logging.getLogger(__name__)

# Tool names must match MCP registry ids where a twin exists.
AWI_HTTP_TOOL_CREDITS: dict[str, Decimal] = {
    "awi_passkey_challenge": Decimal("1"),
    "awi_passkey_verify": Decimal("2"),
    "awi_rag_query": Decimal("3"),
    "awi_memory_index": Decimal("5"),
    "awi_execute": Decimal("3"),
    "awi_dom_sync": Decimal("3"),
}


@dataclass
class AwiHttpGovernedContext:
    """Validated permit context for one AWI HTTP action."""

    auth: AuthContext
    wallet_id: str
    permit_id: str
    idempotency_key: str
    tool_name: str
    credits: Decimal
    permit: PermitModel
    endpoint: str
    #: Identity of this request's idempotency record. Used as the ledger
    #: ``operation_key`` so a retried charge is deduplicated by the database
    #: rather than by hoping the first attempt's outcome was observed.
    record_id: str | None = None
    replay_response: dict[str, Any] | None = None
    replay_status_code: int | None = None


def _credits_for(tool_name: str) -> Decimal:
    return AWI_HTTP_TOOL_CREDITS.get(tool_name, Decimal("1"))


def consume_awi_http_replay(ctx: AwiHttpGovernedContext) -> dict[str, Any] | None:
    """
    Return a prior success body, or re-raise a prior failure status.

    Handlers should call this immediately after ``begin_awi_http_governed``.
    """
    if ctx.replay_response is None:
        return None
    status_code = ctx.replay_status_code or 200
    if status_code >= 400:
        detail = ctx.replay_response.get("detail", ctx.replay_response)
        raise HTTPException(status_code=status_code, detail=detail)
    return ctx.replay_response


def _context_from_validation(
    *,
    auth: AuthContext,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
    tool_name: str,
    credits: Decimal,
    permit: PermitModel,
    endpoint: str,
    record_id: str | None = None,
    replay: IdempotencyReplay | None = None,
) -> AwiHttpGovernedContext:
    return AwiHttpGovernedContext(
        auth=auth,
        wallet_id=wallet_id,
        permit_id=permit_id,
        idempotency_key=idempotency_key,
        tool_name=tool_name,
        credits=credits,
        permit=permit,
        endpoint=endpoint,
        record_id=record_id,
        replay_response=replay.response_json if replay else None,
        replay_status_code=replay.status_code if replay else None,
    )


async def begin_awi_http_governed(
    *,
    auth: AuthContext,
    wallet_id: str | None,
    tool_name: str,
    endpoint: str,
    permit_id: str | None,
    idempotency_key: str | None,
    request_payload: dict[str, Any] | None = None,
) -> AwiHttpGovernedContext:
    """
    Validate permit + idempotency for an AWI HTTP action.

    Clients must send ``X-Permit-Id`` and ``Idempotency-Key``.
    """
    if not wallet_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "wallet_required",
                "message": "Governed AWI actions require a wallet-scoped session or X-Wallet-Id.",
            },
        )

    auth.require_wallet_access(wallet_id)

    if not permit_id or not permit_id.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permit_required",
                "message": (
                    "This AWI HTTP route requires a signed permit "
                    "(header X-Permit-Id). Prefer governed MCP tools when available."
                ),
                "tool": tool_name,
            },
        )

    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "idempotency_key_required",
                "message": "Governed AWI actions require an Idempotency-Key header.",
                "tool": tool_name,
            },
        )

    credits = _credits_for(tool_name)
    validation = await get_permit_service().validate_for_action(
        permit_id=permit_id.strip(),
        wallet_id=wallet_id,
        tool_name=tool_name,
        estimated_credits=credits,
        key_id=auth.key_id,
    )
    if not validation.allowed or validation.permit is None:
        detail: dict[str, Any] = {
            "error": validation.reason or "permit_denied",
            "message": validation.reason or "permit_denied",
            "tool": tool_name,
        }
        if validation.details:
            detail["details"] = validation.details
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )

    idem = get_idempotency_service()
    try:
        begun = await idem.begin_with_record(
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key.strip(),
            request_payload=request_payload
            or {
                "tool_name": tool_name,
                "wallet_id": wallet_id,
                "permit_id": permit_id.strip(),
            },
        )
        replay = begun.replay
        record_id = begun.record_id
    except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": str(exc), "message": str(exc)},
        ) from exc

    if replay and replay.response_json:
        return _context_from_validation(
            auth=auth,
            wallet_id=wallet_id,
            permit_id=permit_id.strip(),
            idempotency_key=idempotency_key.strip(),
            tool_name=tool_name,
            credits=credits,
            permit=validation.permit,
            endpoint=endpoint,
            record_id=record_id,
            replay=replay,
        )

    return _context_from_validation(
        auth=auth,
        wallet_id=wallet_id,
        permit_id=permit_id.strip(),
        idempotency_key=idempotency_key.strip(),
        tool_name=tool_name,
        credits=credits,
        permit=validation.permit,
        endpoint=endpoint,
        record_id=record_id,
    )


async def complete_awi_http_governed(
    ctx: AwiHttpGovernedContext,
    *,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    money: AgentMoney | None = None,
) -> dict[str, Any]:
    """Charge wallet, reserve permit budget, write receipt, complete idempotency."""
    if ctx.replay_response is not None:
        return ctx.replay_response

    from app.services.agent_money import DEFAULT_PRICING, InsufficientFundsResponse

    money = money or get_agent_money()
    permits = get_permit_service()
    idem = get_idempotency_service()
    await permits.reserve_budget(ctx.permit_id, ctx.credits)

    unit_price = DEFAULT_PRICING[ServiceCategory.AGENT_COMMS][1]
    charge_units = ctx.credits / unit_price if unit_price else Decimal("1")

    try:
        charge_result = await money.charge(
            wallet_id=ctx.wallet_id,
            service_category=ServiceCategory.AGENT_COMMS,
            units=charge_units,
            request_path=ctx.endpoint,
            description=f"AWI HTTP {ctx.tool_name}",
            # Key the debit to this request's durable identity. Without it this
            # path had neither the uq_ledger_wallet_operation_key constraint nor
            # the adopt-the-existing-debit recovery that the governed MCP path
            # relies on -- so a charge that committed but whose acknowledgement
            # was lost took the except branch below, which releases budget and
            # *completes* the idempotency record as charge_failed. The caller
            # then retried under a fresh key and was debited a second time for
            # one logical action. With the key, the second attempt adopts the
            # first durable debit instead of creating one.
            operation_key=ctx.record_id,
        )
    except Exception as exc:
        await permits.release_budget(ctx.permit_id, ctx.credits)
        detail = {
            "error": "charge_failed",
            "message": "Wallet charge failed for governed AWI action.",
            "tool": ctx.tool_name,
        }
        await abort_awi_http_governed(ctx, status_code=500, error_payload=detail)
        # Raise HTTPException so route handlers do not re-abort with a
        # different detail (except HTTPException: raise).
        raise HTTPException(status_code=500, detail=detail) from exc

    if isinstance(charge_result, InsufficientFundsResponse):
        await permits.release_budget(ctx.permit_id, ctx.credits)
        detail = {
            "error": "insufficient_funds",
            "message": "Wallet cannot cover governed AWI action.",
            "tool": ctx.tool_name,
        }
        await abort_awi_http_governed(
            ctx, status_code=status.HTTP_402_PAYMENT_REQUIRED, error_payload=detail
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=detail,
        )

    ledger_entry_id = getattr(charge_result, "entry_id", None)
    raw_amount = getattr(charge_result, "amount", ctx.credits)
    try:
        credits_charged = aligned_credits_charged(
            ledger_amount=raw_amount,
            authorized_credits=ctx.credits,
            context=f"awi_http:{ctx.tool_name}",
        )
    except ChargeCreditMismatchError as mismatch_exc:
        if ledger_entry_id:
            await idem.mark_charged(
                wallet_id=ctx.wallet_id,
                endpoint=ctx.endpoint,
                idempotency_key=ctx.idempotency_key,
                ledger_entry_id=str(ledger_entry_id),
            )
        # Wallet was debited: keep permit budget reserved; close the key.
        detail = {
            "error": "charge_credit_mismatch",
            "message": str(mismatch_exc),
            "tool": ctx.tool_name,
        }
        await abort_awi_http_governed(ctx, status_code=500, error_payload=detail)
        raise HTTPException(status_code=500, detail=detail) from mismatch_exc

    if ledger_entry_id:
        await idem.mark_charged(
            wallet_id=ctx.wallet_id,
            endpoint=ctx.endpoint,
            idempotency_key=ctx.idempotency_key,
            ledger_entry_id=str(ledger_entry_id),
        )

    # Finalization is retried as a unit — charge is already checkpointed.
    # Re-load any receipt already written for this ledger entry so a failed
    # refresh/return after commit cannot create a duplicate on retry.
    finalize_attempts = 3
    receipt = None
    if ledger_entry_id:
        receipt = await get_receipt_service().get_receipt_by_ledger_entry_id(
            str(ledger_entry_id)
        )
    response_with_receipt: dict[str, Any] | None = None
    last_exc: Exception | None = None
    for attempt in range(1, finalize_attempts + 1):
        try:
            if receipt is None:
                receipt = await get_receipt_service().create_receipt(
                    permit_id=ctx.permit_id,
                    wallet_id=ctx.wallet_id,
                    key_id=ctx.auth.key_id,
                    tool=ctx.tool_name,
                    request_payload=request_payload,
                    response_payload=response_payload,
                    ledger_entry_id=ledger_entry_id,
                    credits_authorized=ctx.credits,
                    credits_charged=credits_charged,
                    outcome="success",
                    audit_event_id=None,
                    reason_code=None,
                )
            assert receipt is not None
            receipt_payload = {
                "receipt_id": receipt.receipt_id,
                "permit_id": receipt.permit_id,
                "ledger_entry_id": receipt.ledger_entry_id,
                "outcome": receipt.outcome,
                "signature": receipt.signature,
            }
            response_with_receipt = {
                **response_payload,
                "receipt": receipt_payload,
            }
            await idem.complete(
                wallet_id=ctx.wallet_id,
                endpoint=ctx.endpoint,
                idempotency_key=ctx.idempotency_key,
                response_reference=receipt.receipt_id,
                response_json=response_with_receipt,
                status_code=200,
            )
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if receipt is None and ledger_entry_id:
                # Commit may have succeeded even if create_receipt raised later.
                receipt = await get_receipt_service().get_receipt_by_ledger_entry_id(
                    str(ledger_entry_id)
                )
            if attempt == finalize_attempts:
                break
            logger.warning(
                "awi_http_finalize_retry attempt=%d/%d ledger_entry_id=%s error=%s",
                attempt,
                finalize_attempts,
                ledger_entry_id,
                exc,
            )
            await asyncio.sleep(0.05 * attempt)

    if last_exc is not None:
        logger.error(
            "awi_http_finalize_failed_after_retries ledger_entry_id=%s wallet_id=%s error=%s",
            ledger_entry_id,
            ctx.wallet_id,
            last_exc,
        )
        raise last_exc

    assert response_with_receipt is not None
    return response_with_receipt


async def abort_awi_http_governed(
    ctx: AwiHttpGovernedContext,
    *,
    status_code: int,
    error_payload: dict[str, Any],
) -> None:
    """Close an in-progress idempotency key after a failed governed AWI attempt."""
    if ctx.replay_response is not None:
        return
    await get_idempotency_service().complete(
        wallet_id=ctx.wallet_id,
        endpoint=ctx.endpoint,
        idempotency_key=ctx.idempotency_key,
        response_reference=None,
        response_json={"detail": error_payload},
        status_code=status_code,
    )


async def raise_awi_http_error(
    ctx: AwiHttpGovernedContext,
    *,
    status_code: int,
    detail: dict[str, Any],
) -> None:
    """Abort idempotency then raise HTTPException (never returns)."""
    await abort_awi_http_governed(ctx, status_code=status_code, error_payload=detail)
    raise HTTPException(status_code=status_code, detail=detail)


def parse_governed_headers(
    x_permit_id: str | None = Header(None, alias="X-Permit-Id"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_wallet_id: str | None = Header(None, alias="X-Wallet-Id"),
) -> dict[str, str | None]:
    """Optional FastAPI dependency returning governance headers."""
    return {
        "permit_id": x_permit_id,
        "idempotency_key": idempotency_key,
        "wallet_id": x_wallet_id,
    }
