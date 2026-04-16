"""
Notification Service
Sends alerts via Resend (email) and Slack (webhooks).

Used for:
- Wallet frozen alerts (anomalous spend, KYC rejection)
- Low balance warnings (auto_refill_threshold breached)
- Payment failed notifications
"""

import logging
from decimal import Decimal
from typing import Optional

import httpx

from ..core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class NotificationService:
    """
    Sends alerts via email (Resend) and Slack webhooks.

    Primary channel for urgent alerts (wallet frozen, payment failed) is Slack.
    Email is used for sponsor-facing notifications.
    """

    def __init__(self):
        self._resend_api_key = settings.RESEND_API_KEY
        self._slack_webhook_url = settings.SLACK_WEBHOOK_URL
        self._from_email = settings.ALERT_FROM_EMAIL
        self._http = httpx.AsyncClient(timeout=30.0)

    async def send_wallet_frozen_alert(
        self,
        wallet_id: str,
        reason: str,
        sponsor_email: Optional[str] = None,
        wallet_owner: Optional[str] = None,
    ) -> None:
        """
        Send urgent alert when a wallet is frozen.

        Args:
            wallet_id: The frozen wallet ID
            reason: Why it was frozen (anomalous_spend, kyc_rejected, etc.)
            sponsor_email: Email to send alert to
            wallet_owner: Human-readable owner name
        """
        reason_messages = {
            "anomalous_spend": "Anomalous spend velocity detected",
            "kyc_rejected": "KYC/KYB verification rejected",
            "manual_freeze": "Manual freeze by administrator",
            "fraud_detected": "Potential fraud detected",
        }

        subject = f"[B2A Alert] Wallet {wallet_id} Frozen"
        message = reason_messages.get(reason, f"Wallet frozen: {reason}")

        if self._slack_webhook_url:
            await self._send_slack_alert(
                title=subject,
                message=message,
                wallet_id=wallet_id,
                urgency="high",
            )

        if sponsor_email and self._resend_api_key:
            await self._send_email(
                to=sponsor_email,
                subject=subject,
                body=f"""
Your agent wallet {wallet_id} has been frozen.

Reason: {message}
Wallet Owner: {wallet_owner or 'N/A'}

Please log in to the B2A Dashboard to review the alert and take action.

This is an automated alert from the Agent-Native Middleware Platform.
                """.strip(),
            )

    async def send_low_balance_warning(
        self,
        wallet_id: str,
        current_balance: Decimal,
        threshold: Decimal,
        sponsor_email: Optional[str] = None,
    ) -> None:
        """
        Notify sponsor when balance drops below threshold.

        Args:
            wallet_id: The low-balance wallet
            current_balance: Current credit balance
            threshold: The auto_refill_threshold that was breached
            sponsor_email: Email to send warning to
        """
        subject = f"[B2A] Low Balance Warning for Wallet {wallet_id}"
        message = (
            f"Balance: {current_balance} credits "
            f"(threshold: {threshold})"
        )

        if self._slack_webhook_url:
            await self._send_slack_alert(
                title=subject,
                message=message,
                wallet_id=wallet_id,
                urgency="medium",
            )

        if sponsor_email and self._resend_api_key:
            await self._send_email(
                to=sponsor_email,
                subject=subject,
                body=f"""
Your wallet {wallet_id} balance is running low.

Current Balance: {current_balance} credits
Threshold: {threshold} credits

Consider topping up to ensure uninterrupted agent operation.
                """.strip(),
            )

    async def send_payment_failed_alert(
        self,
        wallet_id: str,
        error_message: str,
        payment_intent_id: str,
    ) -> None:
        """
        Notify when a fiat top-up payment fails.

        Args:
            wallet_id: The wallet that attempted top-up
            error_message: Stripe error description
            payment_intent_id: The failed PaymentIntent ID
        """
        subject = f"[B2A] Payment Failed for Wallet {wallet_id}"

        if self._slack_webhook_url:
            await self._send_slack_alert(
                title=subject,
                message=f"Payment failed: {error_message}",
                wallet_id=wallet_id,
                payment_intent_id=payment_intent_id,
                urgency="high",
            )

    async def _send_slack_alert(
        self,
        title: str,
        message: str,
        **fields,
    ) -> None:
        """Send formatted alert to Slack webhook."""
        if not self._slack_webhook_url:
            return

        urgency = fields.get("urgency", "medium")
        urgency_emoji = {
            "high": ":rotating_light:",
            "medium": ":warning:",
            "low": ":information_source:",
        }.get(urgency, "")

        payload = {
            "text": f"{urgency_emoji} {title}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{urgency_emoji} {title}"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Wallet:* {fields.get('wallet_id', 'N/A')}",
                        }
                    ],
                },
            ],
        }

        if "payment_intent_id" in fields:
            payload["blocks"][2]["elements"].append(
                {
                    "type": "mrkdwn",
                    "text": f"*PaymentIntent:* {fields['payment_intent_id']}",
                }
            )

        try:
            resp = await self._http.post(
                self._slack_webhook_url,
                json=payload,
            )
            resp.raise_for_status()
            logger.info(f"Slack alert sent: {title}")
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")

    async def _send_email(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> None:
        """Send email via Resend API."""
        if not self._resend_api_key:
            logger.debug(f"Resend not configured, skipping email to {to}")
            return

        try:
            resp = await self._http.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self._resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._from_email,
                    "to": to,
                    "subject": subject,
                    "text": body,
                },
            )
            resp.raise_for_status()
            logger.info(f"Alert email sent to {to}")
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")

    async def close(self) -> None:
        """Close HTTP client on shutdown."""
        await self._http.aclose()


_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get or create the NotificationService singleton."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
