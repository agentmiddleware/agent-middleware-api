"""
Stripe Webhook Router
Receives and processes Stripe webhook events.

Webhook URL for production: https://api.yourdomain.com/v1/webhooks/stripe
Local development: stripe listen --forward-to localhost:8000/v1/webhooks/stripe
"""

import logging
from fastapi import APIRouter, Request, HTTPException, status

from ..services.stripe_integration import get_stripe_integration

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/webhooks",
    tags=["Webhooks"],
)


@router.post("/stripe")
async def handle_stripe_webhook(request: Request):
    """
    Receive and process Stripe webhook events.

    Stripe will retry this endpoint if we return non-200.
    Our service layer handles idempotency internally via
    UNIQUE constraint on payment_intent_id + IntegrityError catch.

    Events handled:
    - payment_intent.succeeded → Mint credits to wallet
    - payment_intent.payment_failed → Log and notify
    - charge.refunded → Debit wallet
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe signature",
        )

    stripe_integration = get_stripe_integration()
    success = await stripe_integration.handle_webhook(payload, sig_header)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        )

    return {"status": "received"}
