"""Signed quotes — ask what a call costs, get a price you can rely on.

    POST /v1/quotes         issue a signed quote for (wallet, tool)
    GET  /v1/quotes/{id}    read it back

Spending happens on the governed invoke: pass the quote id in
``mcpContext.quote_id`` and the charge uses the quoted credits. See
``docs/signed-quotes.md``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.billing import ServiceCategory
from app.schemas.trust import QuoteCreateRequest, QuoteResponse
from app.services.service_registry import get_service_registry
from app.trust import QuoteError, get_quote_service, tool_price

router = APIRouter(prefix="/v1/quotes", tags=["Trust Permits"])


@router.post("", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def create_quote(
    request: QuoteCreateRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> QuoteResponse:
    """Quote one call of a tool for a wallet the caller owns.

    The price is read from the tool's live registration and frozen into a
    signed statement. No idempotency key: quoting is free, has no side effect
    on the wallet, and a duplicate quote is simply a second unspent
    commitment that expires on its own.
    """
    auth.require_wallet_access(request.wallet_id)

    registry = get_service_registry()
    service = registry.get_local(request.tool)
    if not service:
        service = await registry.get_persistent(request.tool)
    if not service:
        raise HTTPException(status_code=404, detail="tool_not_found")

    category = ServiceCategory(
        service.get("category", ServiceCategory.PLATFORM_FEE.value)
    )
    try:
        return await get_quote_service().create_quote(
            wallet_id=request.wallet_id,
            tool=request.tool,
            quoted_credits=tool_price(service, category),
            category=category.value,
        )
    except QuoteError as exc:
        raise HTTPException(status_code=400, detail=exc.reason)


@router.get("/{quote_id}", response_model=QuoteResponse)
async def get_quote(
    quote_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> QuoteResponse:
    quote = await get_quote_service().get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="quote_not_found")
    auth.require_wallet_access(quote.wallet_id)
    return quote
