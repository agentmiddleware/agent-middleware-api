"""Shared Stripe webhook signature verification.

Both the settlement webhook (StripeIntegration.handle_webhook) and the KYC
webhook (KYCService.handle_webhook) verify the same Stripe signing secret.
They previously did so with separate inline ``construct_event`` blocks, so a
fix to one (for example, naming ``SignatureVerificationError``, which is not
a ``ValueError`` subclass) could silently miss the other. This helper is the
single place that turns a raw payload plus signature header into a verified
event, or ``None`` when verification fails.
"""

import logging
from typing import Any

import stripe

logger = logging.getLogger(__name__)


def verify_stripe_event(payload: bytes, sig_header: str, secret: str) -> Any | None:
    """Verify a Stripe webhook payload against the signing secret.

    Returns the verified event on success, or ``None`` when the signature
    is invalid or the payload is malformed. Callers treat ``None`` as a
    400-level rejection and must not dispatch any handler.
    """
    try:
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        logger.error("Invalid Stripe signature: %s", exc)
        return None
