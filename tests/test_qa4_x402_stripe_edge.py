"""Edge-case QA for the x402 facilitator and the Stripe fiat surface.

Tests only, no product changes: both modules are owned by in-flight work.
Stripe network calls are mocked, no sleeps, no live webhooks.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.stripe_integration import (
    StripeIntegration,
    StripeSettlementError,
)
from app.services.x402_engine import X402Error, get_x402_handler

EVM_PAY_TO = "0x1111111111111111111111111111111111111111"
EVM_PAYER = "0x2222222222222222222222222222222222222222"
SOLANA_PAY_TO = "A" * 40


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


# ---------------------------------------------------------------------------
# x402 requirement validation
# ---------------------------------------------------------------------------


def test_build_requirement_accepts_decimal_input_and_base_units():
    handler = get_x402_handler()
    req = handler.build_requirement(
        amount=Decimal("1.50"), pay_to=EVM_PAY_TO, network="base"
    )
    assert req.amount_usd == Decimal("1.50")
    assert req.amount_base_units == 1500000
    dust = handler.build_requirement(
        amount=Decimal("0.000001"), pay_to=EVM_PAY_TO, network="base"
    )
    assert dust.amount_base_units == 1


def test_build_requirement_normalizes_padded_asset_and_rejects_case():
    handler = get_x402_handler()
    req = handler.build_requirement(
        amount="1.00", pay_to=EVM_PAY_TO, network="base", asset=" USDC "
    )
    assert req.asset == "USDC"
    for bad_asset in ("usdc", "Usdc", "", "DAI"):
        with pytest.raises(X402Error) as exc:
            handler.build_requirement(
                amount="1.00", pay_to=EVM_PAY_TO, network="base", asset=bad_asset
            )
        assert exc.value.reason == "x402_asset_unsupported"


def test_build_requirement_network_whitespace_ok_case_rejected():
    handler = get_x402_handler()
    req = handler.build_requirement(
        amount="1.00", pay_to="  " + EVM_PAY_TO + "  ", network=" base "
    )
    assert req.network == "base"
    assert req.pay_to == EVM_PAY_TO
    with pytest.raises(X402Error) as exc:
        handler.build_requirement(amount="1.00", pay_to=EVM_PAY_TO, network="Base")
    assert exc.value.reason == "x402_network_unsupported"


def test_build_requirement_decimal_edge_amounts():
    handler = get_x402_handler()
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(X402Error) as exc:
            handler.build_requirement(amount=bad, pay_to=EVM_PAY_TO, network="base")
        assert exc.value.reason == "x402_amount_invalid"
    ceiling = handler.build_requirement(
        amount="10000", pay_to=EVM_PAY_TO, network="base"
    )
    assert ceiling.amount_base_units == 10_000_000_000
    with pytest.raises(X402Error) as exc:
        handler.build_requirement(
            amount="10000.000001", pay_to=EVM_PAY_TO, network="base"
        )
    assert exc.value.reason == "x402_amount_too_large"
    with pytest.raises(X402Error) as exc:
        handler.build_requirement(amount="0.0000001", pay_to=EVM_PAY_TO, network="base")
    assert exc.value.reason == "x402_amount_precision_exceeded"


def test_parse_402_accepts_lowercase_header_names():
    handler = get_x402_handler()
    req = handler.parse_402(
        402,
        {
            "x-402-amount": "1.50",
            "x-402-payto": EVM_PAY_TO,
            "x-402-network": "base",
        },
    )
    assert req.amount_usd == Decimal("1.50")
    assert req.pay_to == EVM_PAY_TO
    assert req.network == "base"


def test_derive_nonce_is_deterministic_hex():
    handler = get_x402_handler()
    first = handler._derive_nonce_hex("permit-1", "key-1")
    assert first == handler._derive_nonce_hex("permit-1", "key-1")
    assert len(first) == 64
    int(first, 16)
    assert handler._derive_nonce_hex("permit-1", "key-2") != first
    assert handler._derive_nonce_hex("permit-2", "key-1") != first


# ---------------------------------------------------------------------------
# x402 transfer authorization shapes
# ---------------------------------------------------------------------------


def test_evm_authorization_requires_window_payer_and_binds_nonce():
    handler = get_x402_handler()
    req = handler.build_requirement(amount="1.00", pay_to=EVM_PAY_TO, network="base")
    with pytest.raises(X402Error) as exc:
        handler.build_transfer_authorization(
            req, permit_id="p", wallet_id="w", idempotency_key="k", payer=EVM_PAYER
        )
    assert exc.value.reason == "x402_validity_window_required"
    with pytest.raises(X402Error) as exc:
        handler.build_transfer_authorization(
            req,
            permit_id="p",
            wallet_id="w",
            idempotency_key="k",
            valid_after=0,
            valid_before=99,
        )
    assert exc.value.reason == "x402_payer_required"
    with pytest.raises(X402Error) as exc:
        handler.build_transfer_authorization(
            req,
            permit_id="p",
            wallet_id="w",
            idempotency_key="k",
            payer="0xzz",
            valid_after=0,
            valid_before=99,
        )
    assert exc.value.reason == "x402_payer_invalid"
    auth = handler.build_transfer_authorization(
        req,
        permit_id="permit-9",
        wallet_id="wallet-9",
        idempotency_key="idem-9",
        payer="  " + EVM_PAYER + "  ",
        valid_after=5,
        valid_before=95,
    )
    assert auth["primaryType"] == "TransferWithAuthorization"
    assert auth["domain"]["chainId"] == 8453
    assert auth["domain"]["verifyingContract"] == (
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    )
    assert auth["message"]["from"] == EVM_PAYER
    assert auth["message"]["to"] == EVM_PAY_TO
    assert auth["message"]["value"] == "1000000"
    assert auth["message"]["validAfter"] == "5"
    assert auth["message"]["validBefore"] == "95"
    assert auth["message"]["nonce"] == (
        "0x" + handler._derive_nonce_hex("permit-9", "idem-9")
    )


def test_solana_authorization_shape_with_and_without_payer():
    handler = get_x402_handler()
    req = handler.build_requirement(
        amount="2.50", pay_to=SOLANA_PAY_TO, network="solana"
    )
    bare = handler.build_transfer_authorization(
        req, permit_id="permit-s", wallet_id="wallet-s", idempotency_key="idem-s"
    )
    assert bare["scheme"] == "x402-solana-transfer/1"
    assert bare["network"] == "solana"
    assert bare["asset"] == "USDC"
    assert bare["amount"] == "2500000"
    assert bare["decimals"] == 6
    assert bare["memo"] == "awi-permit:permit-s"
    assert bare["valid_before"] is None
    assert "payer" not in bare
    with_payer = handler.build_transfer_authorization(
        req,
        permit_id="permit-s",
        wallet_id="wallet-s",
        idempotency_key="idem-s",
        payer="  " + SOLANA_PAY_TO + "  ",
        valid_after=7,
        valid_before=77,
    )
    assert with_payer["payer"] == SOLANA_PAY_TO
    assert with_payer["valid_after"] == "7"
    assert with_payer["valid_before"] == "77"
    with pytest.raises(X402Error) as exc:
        handler.build_transfer_authorization(
            req,
            permit_id="permit-s",
            wallet_id="wallet-s",
            idempotency_key="idem-s",
            payer="0x1234",
        )
    assert exc.value.reason == "x402_payer_invalid"


# ---------------------------------------------------------------------------
# Stripe top-up intent validation (no DB: these fail before any lookup)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_top_up_rejects_bad_amounts_without_calling_stripe():
    integration = StripeIntegration()
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        for bad in (
            Decimal("0"),
            Decimal("-5"),
            Decimal("10.001"),
            Decimal("NaN"),
            Decimal("Infinity"),
        ):
            with pytest.raises(ValueError, match="invalid_top_up_amount"):
                await integration.create_top_up_intent(
                    wallet_id="wallet-never-looked-up", amount_fiat=bad
                )
        for bad_currency in ("eur", "", "USDD"):
            with pytest.raises(ValueError, match="unsupported_top_up_currency"):
                await integration.create_top_up_intent(
                    wallet_id="wallet-never-looked-up",
                    amount_fiat=Decimal("5"),
                    currency=bad_currency,
                )
    mock_create.assert_not_called()


@pytest.mark.anyio
async def test_create_top_up_accepts_uppercase_currency_and_single_cent(
    client, api_headers, clean_database
):
    # Service level: the /top-up/prepare route lives on the dormant
    # expansion router, which conftest only mounts for listed modules,
    # so this module exercises the service directly. The sponsor wallet
    # itself is created through the core billing router, which is mounted.
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "QA Edge Sponsor",
            "email": "qa-edge@b2a.dev",
            "initial_credits": 0,
        },
        headers=api_headers,
    )
    assert sponsor.status_code == 201, sponsor.text
    wallet_id = sponsor.json()["wallet_id"]
    integration = StripeIntegration()
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        mock_create.return_value = MagicMock(
            id="pi_edge_cent",
            client_secret="pi_edge_cent_secret",
            status="requires_payment_method",
        )
        result = await integration.create_top_up_intent(
            wallet_id=wallet_id,
            amount_fiat=Decimal("0.01"),
            currency="USD",
        )
        assert result["currency"] == "USD"
        assert result["amount_credits"] == 10
        assert result["amount_fiat"] == 0.01
        assert result["payment_intent_id"] == "pi_edge_cent"
        assert result["client_secret"] == "pi_edge_cent_secret"
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["amount"] == 1
        assert call_kwargs["currency"] == "usd"
        assert call_kwargs["metadata"]["wallet_id"] == wallet_id
        assert call_kwargs["metadata"]["credits"] == "10"


# ---------------------------------------------------------------------------
# Stripe ACP charge and cancel helpers (no wallets, no ledger, no network)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_charge_shared_token_rejects_bad_input_without_calling_stripe():
    integration = StripeIntegration()
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create"
    ) as mock_create:
        with pytest.raises(ValueError, match="unsupported_acp_currency"):
            await integration.charge_shared_payment_token(
                spt_token="spt_x",
                amount_minor=100,
                currency="eur",
                idempotency_key="k",
            )
        for bad_amount in (0, -50, True, False, "100", 10.5):
            with pytest.raises(ValueError, match="invalid_acp_charge_amount"):
                await integration.charge_shared_payment_token(
                    spt_token="spt_x",
                    amount_minor=bad_amount,
                    currency="usd",
                    idempotency_key="k",
                )
        with pytest.raises(ValueError, match="missing_shared_payment_token"):
            await integration.charge_shared_payment_token(
                spt_token="",
                amount_minor=100,
                currency="usd",
                idempotency_key="k",
            )
    mock_create.assert_not_called()


@pytest.mark.anyio
async def test_charge_shared_token_confirms_once_with_idempotency_key():
    integration = StripeIntegration()
    fake_intent = {
        "id": "pi_acp_1",
        "status": "succeeded",
        "amount": 250,
        "currency": "usd",
    }
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.create",
        return_value=fake_intent,
    ) as mock_create:
        result = await integration.charge_shared_payment_token(
            spt_token="spt_secret_token",
            amount_minor=250,
            currency="USD",
            idempotency_key="acp-checkout-1",
        )
    assert result == {
        "payment_intent_id": "pi_acp_1",
        "status": "succeeded",
        "amount": 250,
        "currency": "usd",
    }
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["amount"] == 250
    assert call_kwargs["currency"] == "usd"
    assert call_kwargs["payment_method"] == "spt_secret_token"
    assert call_kwargs["confirm"] is True
    assert call_kwargs["idempotency_key"] == "acp-checkout-1"


@pytest.mark.anyio
async def test_cancel_payment_intent_validation_and_key_passthrough():
    integration = StripeIntegration()
    with pytest.raises(ValueError, match="missing_payment_intent_id"):
        await integration.cancel_payment_intent("")
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.cancel",
        return_value={"id": "pi_cancel_1", "status": "canceled"},
    ) as mock_cancel:
        result = await integration.cancel_payment_intent(
            "pi_cancel_1", idempotency_key="cancel-1"
        )
    assert result == {"payment_intent_id": "pi_cancel_1", "status": "canceled"}
    mock_cancel.assert_called_once_with("pi_cancel_1", idempotency_key="cancel-1")
    with patch(
        "app.services.stripe_integration.stripe.PaymentIntent.cancel",
        return_value={"id": "pi_cancel_2", "status": "canceled"},
    ) as mock_cancel_plain:
        await integration.cancel_payment_intent("pi_cancel_2")
    mock_cancel_plain.assert_called_once_with("pi_cancel_2")


# ---------------------------------------------------------------------------
# Stripe settlement validators (pure unit, no DB, no network)
# ---------------------------------------------------------------------------


def _settled_intent(**overrides):
    intent = {
        "id": "pi_settled_1",
        "status": "succeeded",
        "amount": 5000,
        "amount_received": 5000,
        "currency": "usd",
        "metadata": {"wallet_id": "wallet-1", "credits": "50000"},
    }
    intent.update(overrides)
    return intent


def test_validate_succeeded_intent_settles_exact_credit_math():
    payment_intent_id, wallet_id, credits = (
        StripeIntegration._validate_succeeded_payment_intent(_settled_intent())
    )
    assert payment_intent_id == "pi_settled_1"
    assert wallet_id == "wallet-1"
    assert credits == Decimal("50000")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"id": ""}, "missing_payment_intent_id"),
        ({"status": "requires_payment_method"}, "payment_intent_not_succeeded"),
        ({"currency": "eur"}, "unsupported_top_up_currency"),
        ({"amount_received": 1000}, "payment_intent_amount_mismatch"),
        ({"amount": 0, "amount_received": 0}, "payment_intent_amount_mismatch"),
        ({"amount": True, "amount_received": True}, "payment_intent_amount_mismatch"),
        ({"metadata": None}, "missing_payment_intent_metadata"),
        (
            {"metadata": {"wallet_id": "  ", "credits": "50000"}},
            "missing_wallet_metadata",
        ),
        (
            {"metadata": {"wallet_id": "wallet-1", "credits": "not-a-number"}},
            "invalid_credit_metadata",
        ),
        (
            {"metadata": {"wallet_id": "wallet-1", "credits": "99999999"}},
            "credit_metadata_mismatch",
        ),
    ],
)
def test_validate_succeeded_intent_rejects_each_bad_field(mutation, reason):
    with pytest.raises(StripeSettlementError) as exc:
        StripeIntegration._validate_succeeded_payment_intent(
            _settled_intent(**mutation)
        )
    assert str(exc.value) == reason


def _refund_charge(**overrides):
    charge = {
        "payment_intent": "pi_refund_1",
        "amount": 5000,
        "amount_refunded": 2000,
        "currency": "usd",
        "id": "ch_refund_1",
    }
    charge.update(overrides)
    return charge


def test_validate_refund_charge_happy_path_and_charge_id_fallback():
    parsed = StripeIntegration._validate_refund_charge(_refund_charge())
    assert parsed == ("pi_refund_1", 5000, 2000, "ch_refund_1")
    parsed_no_charge_id = StripeIntegration._validate_refund_charge(
        _refund_charge(id=None)
    )
    assert parsed_no_charge_id[3] is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"payment_intent": ""}, "missing_refund_payment_intent_id"),
        ({"currency": "eur"}, "unsupported_refund_currency"),
        ({"amount": 0}, "invalid_charge_amount"),
        ({"amount": True}, "invalid_charge_amount"),
        ({"amount_refunded": 0}, "invalid_refund_amount"),
        ({"amount_refunded": False}, "invalid_refund_amount"),
        ({"amount_refunded": 6000}, "refund_exceeds_charge_amount"),
    ],
)
def test_validate_refund_charge_rejects_each_bad_field(mutation, reason):
    with pytest.raises(StripeSettlementError) as exc:
        StripeIntegration._validate_refund_charge(_refund_charge(**mutation))
    assert str(exc.value) == reason


def test_stripe_value_reads_dicts_and_missing_keys_safely():
    read = StripeIntegration._stripe_value
    assert read({"a": 1}, "a") == 1
    assert read({"a": 1}, "missing") is None
    assert read({"a": 1}, "missing", "fallback") == "fallback"
    assert read(None, "a") is None
    assert read("not-a-container", "a", "fallback") == "fallback"


def test_only_payment_intent_unique_errors_are_idempotent_for_mint():
    from sqlalchemy.exc import IntegrityError

    def _integrity(message: str) -> IntegrityError:
        return IntegrityError("insert", {}, Exception(message))

    is_dup = StripeIntegration._is_duplicate_payment_intent_error
    assert (
        is_dup(_integrity("UNIQUE constraint failed: ledger.payment_intent_id")) is True
    )
    assert is_dup(_integrity("duplicate key value violates unique constraint")) is False
    assert (
        is_dup(_integrity("null value in column payment_intent_id of relation ledger"))
        is False
    )
    is_evt_dup = StripeIntegration._is_duplicate_stripe_event_error
    assert (
        is_evt_dup(_integrity("UNIQUE constraint failed: ledger.stripe_event_id"))
        is True
    )
    assert (
        is_evt_dup(_integrity("UNIQUE constraint failed: ledger.payment_intent_id"))
        is False
    )


# ---------------------------------------------------------------------------
# Stripe webhook dispatch and failure alerts (no DB, no network)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_webhook_returns_false_on_signature_failure():
    integration = StripeIntegration()
    with patch(
        "app.services.stripe_integration.stripe.Webhook.construct_event",
        side_effect=stripe.SignatureVerificationError("bad sig", "sig"),
    ):
        assert await integration.handle_webhook(b"payload", "sig") is False


@pytest.mark.anyio
async def test_handle_webhook_ignores_unknown_event_types():
    integration = StripeIntegration()
    event = {
        "id": "evt_unknown_1",
        "type": "customer.created",
        "data": {"object": {"id": "cus_1"}},
    }
    with (
        patch(
            "app.services.stripe_integration.stripe.Webhook.construct_event",
            return_value=event,
        ),
        patch.object(
            StripeIntegration, "_handle_payment_success", new_callable=AsyncMock
        ) as mock_success,
        patch.object(
            StripeIntegration, "_handle_refund", new_callable=AsyncMock
        ) as mock_refund,
    ):
        assert await integration.handle_webhook(b"payload", "sig") is True
    mock_success.assert_not_awaited()
    mock_refund.assert_not_awaited()


@pytest.mark.anyio
async def test_handle_webhook_routes_refund_with_event_id():
    integration = StripeIntegration()
    charge = {
        "id": "ch_route_1",
        "payment_intent": "pi_route_1",
        "amount": 5000,
        "amount_refunded": 5000,
        "currency": "usd",
    }
    event = {"id": "evt_route_1", "type": "charge.refunded", "data": {"object": charge}}
    with (
        patch(
            "app.services.stripe_integration.stripe.Webhook.construct_event",
            return_value=event,
        ),
        patch.object(
            StripeIntegration, "_handle_refund", new_callable=AsyncMock
        ) as mock_refund,
    ):
        assert await integration.handle_webhook(b"payload", "sig") is True
    mock_refund.assert_awaited_once_with(charge, "evt_route_1")


@pytest.mark.anyio
async def test_handle_payment_failed_sends_alert_with_intent_details():
    integration = StripeIntegration()
    notifications = MagicMock()
    notifications.send_payment_failed_alert = AsyncMock()
    with patch(
        "app.services.notifications.get_notification_service",
        return_value=notifications,
    ):
        await integration._handle_payment_failed(
            {
                "id": "pi_failed_1",
                "metadata": {"wallet_id": "wallet-9"},
                "last_payment_error": {"message": "card declined"},
            }
        )
    notifications.send_payment_failed_alert.assert_awaited_once_with(
        wallet_id="wallet-9",
        error_message="card declined",
        payment_intent_id="pi_failed_1",
    )


@pytest.mark.anyio
@pytest.mark.xfail(
    strict=True,
    reason="stripe_integration.py:402 subscripts payment_intent[metadata] "
    "directly, so a payment_failed event without a metadata key raises "
    "KeyError instead of failing closed",
)
async def test_handle_payment_failed_without_metadata_key_fails_closed():
    integration = StripeIntegration()
    await integration._handle_payment_failed({"id": "pi_no_metadata"})
