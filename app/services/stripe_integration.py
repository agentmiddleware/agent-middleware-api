"""
Stripe Fiat Ingestion Service
Handles payment intents and webhook processing for fiat top-ups.

Architecture:
1. Client calls /top-up/prepare → creates Stripe PaymentIntent
2. Client completes payment via Stripe.js in browser
3. Stripe sends webhook to /webhooks/stripe
4. Webhook handler mints credits to the wallet
5. If Stripe retries webhook, IntegrityError is caught for idempotency
"""

import logging
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import stripe
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from ..db.database import get_session_factory
from ..db.models import WalletModel, LedgerEntryModel
from ..core.config import get_settings
from .agent_money import WalletNotFoundError

logger = logging.getLogger(__name__)
settings = get_settings()

stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeIntegration:
    """
    Handles fiat top-ups via Stripe Payment Intents.

    Uses async SQLAlchemy sessions for non-blocking database operations.
    Implements idempotency via UNIQUE constraint on payment_intent_id.
    """

    def __init__(self):
        self._session_factory = get_session_factory

    async def create_top_up_intent(
        self,
        wallet_id: str,
        amount_fiat: Decimal,
        currency: str = "usd",
    ) -> dict:
        """
        Create a Stripe PaymentIntent for fiat top-up.

        Args:
            wallet_id: The wallet to credit after successful payment
            amount_fiat: Amount in fiat currency (e.g., 50.00 for $50)
            currency: ISO 4217 currency code (default: usd)

        Returns:
            {
                "client_secret": str,
                "payment_intent_id": str,
                "amount_credits": int,
                "amount_fiat": float,
                "currency": str,
            }
        """
        async with self._session_factory()() as session:
            result = await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )
            wallet = result.scalar_one_or_none()
            if not wallet:
                raise WalletNotFoundError(wallet_id)

        credits = int(amount_fiat * settings.EXCHANGE_RATE)

        intent = stripe.PaymentIntent.create(
            amount=int(amount_fiat * 100),
            currency=currency.lower(),
            metadata={
                "wallet_id": wallet_id,
                "credits": credits,
                "idempotency_key": str(uuid4()),
            },
        )

        logger.info(
            f"Created PaymentIntent {intent.id} for wallet {wallet_id}: "
            f"${amount_fiat} -> {credits} credits"
        )

        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount_credits": credits,
            "amount_fiat": float(amount_fiat),
            "currency": currency.upper(),
        }

    async def handle_webhook(
        self,
        payload: bytes,
        sig_header: str,
    ) -> bool:
        """
        Process Stripe webhook events.

        Args:
            payload: Raw request body bytes
            sig_header: Stripe-Signature header value

        Returns:
            True if processed successfully, False on signature failure
        Raises:
            ValueError: For unhandled event types
        """
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        except ValueError as e:
            logger.error(f"Invalid Stripe signature: {e}")
            return False

        handler_map = {
            "payment_intent.succeeded": self._handle_payment_success,
            "payment_intent.payment_failed": self._handle_payment_failed,
            "charge.refunded": self._handle_refund,
        }

        handler = handler_map.get(event["type"])
        if handler:
            await handler(event["data"]["object"])
        else:
            logger.debug(f"Ignoring unhandled event type: {event['type']}")

        return True

    async def _handle_payment_success(self, payment_intent: dict) -> None:
        """Mint credits when Stripe confirms payment."""
        wallet_id = payment_intent["metadata"].get("wallet_id")
        credits = int(payment_intent["metadata"].get("credits", 0))

        if not wallet_id or not credits:
            logger.error(f"Missing metadata in PaymentIntent {payment_intent['id']}")
            return

        await self._mint_credits(
            wallet_id=wallet_id,
            amount=Decimal(credits),
            payment_intent_id=payment_intent["id"],
            description=f"Fiat top-up via Stripe ({payment_intent['id']})",
        )

        logger.info(
            f"Minted {credits} credits to wallet {wallet_id} "
            f"from PaymentIntent {payment_intent['id']}"
        )

    async def _handle_payment_failed(self, payment_intent: dict) -> None:
        """Log payment failure and notify via Slack."""
        from ..services.notifications import get_notification_service

        wallet_id = payment_intent["metadata"].get("wallet_id")
        error_msg = (
            payment_intent.get("last_payment_error", {}).get("message", "Unknown error")
        )

        logger.warning(f"Payment failed for wallet {wallet_id}: {error_msg}")

        if wallet_id:
            notifications = get_notification_service()
            await notifications.send_payment_failed_alert(
                wallet_id=wallet_id,
                error_message=error_msg,
                payment_intent_id=payment_intent["id"],
            )

    async def _handle_refund(self, charge: dict) -> None:
        """Debit wallet when Stripe issues a refund."""
        payment_intent_id = charge.get("payment_intent")
        if not payment_intent_id:
            return

        async with self._session_factory()() as session:
            result = await session.execute(
                select(LedgerEntryModel).where(
                    LedgerEntryModel.payment_intent_id == payment_intent_id
                )
            )
            entry = result.scalar_one_or_none()
            if not entry:
                logger.warning(
                    f"Cannot find ledger entry for refund {payment_intent_id}"
                )
                return

            refund_amount = Decimal(charge.get("amount", 0)) / Decimal("100")
            credits = int(refund_amount * settings.EXCHANGE_RATE)

            await self._debit_wallet(
                wallet_id=entry.wallet_id,
                amount=Decimal(credits),
                description=f"Refund for PaymentIntent {payment_intent_id}",
            )

    async def _mint_credits(
        self,
        wallet_id: str,
        amount: Decimal,
        payment_intent_id: str,
        description: str,
    ) -> None:
        """
        Mint credits to a wallet with idempotency.

        The UNIQUE constraint on payment_intent_id ensures we never
        double-mint. Catching IntegrityError returns 200 to Stripe
        to stop their retry loop (hybrid Option A+B approach).
        """
        try:
            async with self._session_factory()() as session:
                async with session.begin():
                    result = await session.execute(
                        select(WalletModel)
                        .where(WalletModel.wallet_id == wallet_id)
                        .with_for_update()
                    )
                    wallet = result.scalar_one_or_none()

                    if not wallet:
                        logger.error(f"Wallet not found: {wallet_id}")
                        return

                    wallet.balance += amount
                    wallet.lifetime_credits += amount

                    entry = LedgerEntryModel(
                        entry_id=str(uuid4()),
                        wallet_id=wallet_id,
                        action="credit",
                        amount=amount,
                        balance_after=wallet.balance,
                        payment_intent_id=payment_intent_id,
                        description=description,
                    )
                    session.add(entry)

                await session.commit()

        except IntegrityError:
            logger.info(
                f"Idempotency catch: PaymentIntent {payment_intent_id} "
                f"already processed. Swallowing error to return 200 OK."
            )
            return

    async def _debit_wallet(
        self,
        wallet_id: str,
        amount: Decimal,
        description: str,
    ) -> None:
        """Debit wallet for refunds."""
        async with self._session_factory()() as session:
            async with session.begin():
                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == wallet_id)
                    .with_for_update()
                )
                wallet = result.scalar_one_or_none()

                if not wallet:
                    logger.error(f"Wallet not found: {wallet_id}")
                    return

                wallet.balance -= amount
                wallet.lifetime_debits += amount

                entry = LedgerEntryModel(
                    entry_id=str(uuid4()),
                    wallet_id=wallet_id,
                    action="refund",
                    amount=-amount,
                    balance_after=wallet.balance,
                    description=description,
                )
                session.add(entry)

            await session.commit()


_stripe_integration: Optional[StripeIntegration] = None


def get_stripe_integration() -> StripeIntegration:
    """Get or create the StripeIntegration singleton."""
    global _stripe_integration
    if _stripe_integration is None:
        _stripe_integration = StripeIntegration()
    return _stripe_integration
