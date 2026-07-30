"""
Governed AWI HTTP actions — close the HTTP bypass of the MCP trust spine.

High-risk ``/v1/awi/*`` mutating routes require the same permit + idempotency
headers as governed MCP tools, then meter and receipt the attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import Header, HTTPException, status

from app.core.auth import AuthContext
from app.db.models import PermitModel
from app.schemas.billing import ServiceCategory
from app.services.agent_money import AgentMoney, get_agent_money
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.permits import get_permit_service
from app.services.receipts import get_receipt_service

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
    replay_response: dict[str, Any] | None = None


def _credits_for(tool_name: str) -> Decimal:
    return AWI_HTTP_TOOL_CREDITS.get(tool_name, Decimal("1"))


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": validation.reason or "permit_denied",
                "message": validation.reason or "permit_denied",
                "tool": tool_name,
            },
        )

    idem = get_idempotency_service()
    try:
        replay = await idem.begin(
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
    except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": str(exc), "message": str(exc)},
        ) from exc

    if replay and replay.response_json:
        return AwiHttpGovernedContext(
            auth=auth,
            wallet_id=wallet_id,
            permit_id=permit_id.strip(),
            idempotency_key=idempotency_key.strip(),
            tool_name=tool_name,
            credits=credits,
            permit=validation.permit,
            endpoint=endpoint,
            replay_response=replay.response_json,
        )

    return AwiHttpGovernedContext(
        auth=auth,
        wallet_id=wallet_id,
        permit_id=permit_id.strip(),
        idempotency_key=idempotency_key.strip(),
        tool_name=tool_name,
        credits=credits,
        permit=validation.permit,
        endpoint=endpoint,
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

    from app.services.agent_money import InsufficientFundsResponse

    money = money or get_agent_money()
    permits = get_permit_service()
    await permits.reserve_budget(ctx.permit_id, ctx.credits)

    try:
        charge_result = await money.charge(
            wallet_id=ctx.wallet_id,
            service_category=ServiceCategory.AGENT_COMMS,
            units=Decimal("1"),
            request_path=ctx.endpoint,
            description=f"AWI HTTP {ctx.tool_name}",
        )
    except Exception:
        await permits.release_budget(ctx.permit_id, ctx.credits)
        raise

    if isinstance(charge_result, InsufficientFundsResponse):
        await permits.release_budget(ctx.permit_id, ctx.credits)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_funds",
                "message": "Wallet cannot cover governed AWI action.",
                "tool": ctx.tool_name,
            },
        )

    ledger_entry_id = getattr(charge_result, "entry_id", None)
    raw_amount = getattr(charge_result, "amount", ctx.credits)
    charged = abs(Decimal(str(raw_amount)))

    receipt = await get_receipt_service().create_receipt(
        permit_id=ctx.permit_id,
        wallet_id=ctx.wallet_id,
        key_id=ctx.auth.key_id,
        tool=ctx.tool_name,
        request_payload=request_payload,
        response_payload=response_payload,
        ledger_entry_id=ledger_entry_id,
        credits_authorized=ctx.credits,
        credits_charged=charged,
        outcome="success",
        audit_event_id=None,
    )

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

    await get_idempotency_service().complete(
        wallet_id=ctx.wallet_id,
        endpoint=ctx.endpoint,
        idempotency_key=ctx.idempotency_key,
        response_reference=receipt.receipt_id,
        response_json=response_with_receipt,
        status_code=200,
    )
    return response_with_receipt


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
