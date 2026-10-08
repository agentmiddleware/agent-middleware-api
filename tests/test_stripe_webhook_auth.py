"""Tests for the shared Stripe webhook signature verifier."""

from unittest.mock import patch

import stripe

from app.services.stripe_webhook_auth import verify_stripe_event


def test_verify_returns_event_on_valid_signature():
    sentinel = {"id": "evt_123", "type": "payment_intent.succeeded"}
    with patch(
        "app.services.stripe_webhook_auth.stripe.Webhook.construct_event",
        return_value=sentinel,
    ) as mock_construct:
        assert verify_stripe_event(b"payload", "sig", "whsec_test") is sentinel
    mock_construct.assert_called_once_with(b"payload", "sig", "whsec_test")


def test_verify_returns_none_on_signature_error():
    with patch(
        "app.services.stripe_webhook_auth.stripe.Webhook.construct_event",
        side_effect=stripe.SignatureVerificationError("Invalid signature", "bad_sig"),
    ):
        assert verify_stripe_event(b"payload", "bad_sig", "whsec_test") is None


def test_verify_returns_none_on_malformed_payload():
    with patch(
        "app.services.stripe_webhook_auth.stripe.Webhook.construct_event",
        side_effect=ValueError("bad payload"),
    ):
        assert verify_stripe_event(b"not-json", "sig", "whsec_test") is None


def test_signature_error_is_not_a_value_error():
    # Contract the shared helper depends on: both exception types must be
    # caught, since Stripe's error does not subclass ValueError.
    assert not issubclass(stripe.SignatureVerificationError, ValueError)
