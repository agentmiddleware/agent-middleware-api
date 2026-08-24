"""ACP commerce bridge: checkouts translated into trust-plane bounds.

ACP (Agentic Commerce Protocol) checkouts are translated into PermitV2
tool-execution bounds and settled via Stripe Shared Payment Tokens. The
adapter never mints credits and never writes real ledger entries: the durable
money artifacts it produces are a budget reservation on a purpose-minted
permit, a signed receipt, and a hash-chained audit event. Order ids
(``acp-{intent_id}``) are bound to the tamper-evident audit chain by being
signed into the event's metadata and indexed via ``request_id``.

Settlement-rails conformance (docs/settlement-rails.md):

* item 3 — the charged amount is derived server-side from the line items,
  never from client metadata;
* item 4 — the client-asserted ``client_total`` must equal the derived total
  exactly or the checkout is refused (``acp_total_mismatch``);
* item 5 — currency is validated against a fail-closed allowlist at the
  schema boundary and revalidated by the Stripe helper;
* item 7 — a repeated ``intent_id`` replays the original checkout result via
  the durable idempotency service and provably never charges twice (the
  intent id also rides to Stripe as the PaymentIntent idempotency key).

The ``spt_token`` is never logged and never persisted: it is excluded from
the idempotency request payload, the receipt payloads, and the audit
metadata.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from app.core.config import get_settings
from app.core.time import utc_now
from app.schemas.acp import ACPCheckoutRequest, ACPCheckoutResponse, ACPLineItem
from app.schemas.trust import PermitCreateRequest
from app.services.audit_log import record_audit_event
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.permits import PermitError, get_permit_service
from app.services.receipts import get_receipt_service
from app.services.signing_keys import sha256_hex
from app.services.stripe_integration import get_stripe_integration

ACP_CHECKOUT_TOOL = "acp.checkout"
ACP_CHECKOUT_ENDPOINT = "/v1/billing/acp/checkout"
# Short expiry: the permit exists only to bound this one checkout, so it must
# not remain reservable long after the settlement window has passed.
ACP_PERMIT_TTL = timedelta(minutes=15)
_SETTLED_STRIPE_STATUSES = frozenset({"succeeded"})


class ACPBridgeError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def derive_total_minor(line_items: list[ACPLineItem]) -> int:
    """Server-side total in minor units: sum(quantity * unit_amount)."""
    return sum(item.quantity * item.unit_amount for item in line_items)


def total_minor_to_credits(total_minor: int) -> Decimal:
    """Convert a minor-unit USD amount into internal credits.

    Same formula as the Stripe top-up path: credits = cents * EXCHANGE_RATE
    / 100, with the rate read from settings at call time (never re-declared
    as a module constant).
    """
    return Decimal(total_minor) * get_settings().EXCHANGE_RATE / Decimal("100")


def line_items_digest(line_items: list[ACPLineItem]) -> str:
    """Stable digest of the line items for receipts/idempotency payloads."""
    return sha256_hex(
        {"line_items": [item.model_dump(mode="json") for item in line_items]}
    )


def _audit_request_id(order_id: str) -> str:
    # The audit table's indexed request_id column is capped at 100 chars;
    # order ids derived from a maximum-length intent_id (128 chars) exceed it.
    # Fall back to a deterministic digest rather than a truncation that could
    # collide. The full order id is always in the signed metadata regardless.
    if len(order_id) <= 100:
        return order_id
    return f"acp-{sha256_hex(order_id)}"


def translate_to_permit_bounds(
    request: ACPCheckoutRequest,
    *,
    sponsor_wallet_id: str,
    agent_wallet_id: str,
    key_id: str | None,
) -> PermitCreateRequest:
    """Translate an ACP checkout into PermitV2 creation bounds.

    Pure (no wallet/DB access) so the translation is unit-testable on its
    own: the derived credit budget doubles as both ``max_credits`` and the
    ``aggregate_value_cap``, the tool is single-use via ``max_calls_per_tool``,
    and the merchant hostname becomes the ``recipient_domain`` constraint.
    """
    credits = total_minor_to_credits(derive_total_minor(request.line_items))
    return PermitCreateRequest(
        issuer_wallet_id=sponsor_wallet_id,
        subject_wallet_id=agent_wallet_id,
        subject_key_id=key_id,
        allowed_tools=[ACP_CHECKOUT_TOOL],
        max_credits=credits,
        expires_at=utc_now() + ACP_PERMIT_TTL,
        max_calls_per_tool={ACP_CHECKOUT_TOOL: 1},
        aggregate_value_cap=credits,
        forbidden_fields=[],
        recipient_domain=request.merchant_domain,
    )


class ACPCommerceAdapter:
    """Executes ACP checkouts through the governed trust-plane loop."""

    @staticmethod
    def _idempotency_payload(
        request: ACPCheckoutRequest,
        *,
        sponsor_wallet_id: str,
        agent_wallet_id: str,
        key_id: str | None,
    ) -> dict[str, Any]:
        # Deliberately excludes spt_token: the credential must never be
        # persisted (not even hashed into a stored request identity), and a
        # merchant re-issuing a token for the same intent must still replay
        # the original settled checkout.
        return {
            "intent_id": request.intent_id,
            "sponsor_wallet_id": sponsor_wallet_id,
            "agent_wallet_id": agent_wallet_id,
            "key_id": key_id,
            "merchant_domain": request.merchant_domain,
            "client_total": request.client_total,
            "line_items_digest": line_items_digest(request.line_items),
        }

    @staticmethod
    async def _abandon_intent(*, agent_wallet_id: str, intent_id: str) -> None:
        # Failed checkouts must not pin the intent id forever: abandon only
        # deletes an uncompleted, uncharged record, so a settled checkout's
        # replay is never destroyed by this call.
        await get_idempotency_service().abandon(
            wallet_id=agent_wallet_id,
            endpoint=ACP_CHECKOUT_ENDPOINT,
            idempotency_key=intent_id,
        )

    async def execute_checkout(
        self,
        request: ACPCheckoutRequest,
        *,
        sponsor_wallet_id: str,
        agent_wallet_id: str,
        key_id: str | None,
    ) -> ACPCheckoutResponse:
        """Derive → permit → reserve → charge → audit → receipt, atomically.

        The subject (agent) wallet must hold balance >= the derived credit
        budget: ``create_permit`` refuses otherwise
        (``permit_budget_exceeds_wallet_balance``), so callers must use a
        funded wallet. The wallet itself is never debited here — the permit
        reservation is the economic bound.

        Any failure after the budget reservation releases the exact reserved
        amount and abandons the intent's idempotency record before
        re-raising, so no partial checkout state survives.
        """
        # 1. Server-side total; the client-asserted number is checked for
        # exact equality and never trusted (checklist items 3 and 4).
        total_minor = derive_total_minor(request.line_items)
        if request.client_total != total_minor:
            raise ACPBridgeError("acp_total_mismatch")
        credits = total_minor_to_credits(total_minor)
        derived_total = str(Decimal(total_minor) / Decimal("100"))
        currency = request.line_items[0].currency
        order_id = f"acp-{request.intent_id}"

        # 2. Idempotency on intent_id (checklist item 7): a repeated intent
        # replays the original result and must not reach the charge path.
        idem = get_idempotency_service()
        try:
            begun = await idem.begin_with_record(
                wallet_id=agent_wallet_id,
                endpoint=ACP_CHECKOUT_ENDPOINT,
                idempotency_key=request.intent_id,
                request_payload=self._idempotency_payload(
                    request,
                    sponsor_wallet_id=sponsor_wallet_id,
                    agent_wallet_id=agent_wallet_id,
                    key_id=key_id,
                ),
            )
        except IdempotencyConflictError as exc:
            raise ACPBridgeError("acp_intent_conflict") from exc
        except IdempotencyInProgressError as exc:
            raise ACPBridgeError("acp_intent_in_progress") from exc
        if begun.replay is not None:
            payload = begun.replay.response_json
            if not isinstance(payload, dict):
                raise ACPBridgeError("acp_intent_conflict")
            try:
                return ACPCheckoutResponse.model_validate(payload)
            except ValueError as exc:
                raise ACPBridgeError("acp_intent_conflict") from exc

        # 3. Translate to PermitV2 bounds and mint the single-use permit.
        try:
            permit = await get_permit_service().create_permit(
                translate_to_permit_bounds(
                    request,
                    sponsor_wallet_id=sponsor_wallet_id,
                    agent_wallet_id=agent_wallet_id,
                    key_id=key_id,
                )
            )
        except PermitError as exc:
            await self._abandon_intent(
                agent_wallet_id=agent_wallet_id, intent_id=request.intent_id
            )
            raise ACPBridgeError(exc.reason) from exc

        # 4. Atomic authorize + budget reservation under the permit.
        validation = await get_permit_service().authorize_and_reserve(
            permit_id=permit.permit_id,
            wallet_id=agent_wallet_id,
            tool_name=ACP_CHECKOUT_TOOL,
            estimated_credits=credits,
            key_id=key_id,
            arguments={
                "merchant_domain": request.merchant_domain,
                "intent_id": request.intent_id,
            },
        )
        if not validation.allowed:
            await self._abandon_intent(
                agent_wallet_id=agent_wallet_id, intent_id=request.intent_id
            )
            raise ACPBridgeError(validation.reason or "acp_authorization_denied")

        # 5. From here on, every failure must release the exact reservation
        # (and free the intent id) before re-raising: no partial state.
        async def _rollback() -> None:
            await get_permit_service().release_budget(permit.permit_id, credits)
            await self._abandon_intent(
                agent_wallet_id=agent_wallet_id, intent_id=request.intent_id
            )

        # 6. Outbound settlement via the Shared Payment Token. The intent id
        # rides to Stripe as the PaymentIntent idempotency key, so even a
        # crash-retry that reaches Stripe twice cannot charge twice.
        try:
            charge = await get_stripe_integration().charge_shared_payment_token(
                spt_token=request.spt_token,
                amount_minor=total_minor,
                currency=currency,
                idempotency_key=order_id,
            )
            if charge.get("status") not in _SETTLED_STRIPE_STATUSES:
                raise RuntimeError("acp_spt_not_settled")
        except Exception as exc:
            await _rollback()
            raise ACPBridgeError("acp_spt_charge_failed") from exc

        try:
            # 7. Bind the order to the tamper-evident chain: the order id is
            # signed into the metadata (payload_hash → signature → chain
            # hash) and indexed via request_id for lookup.
            event = await record_audit_event(
                event="acp_checkout_settled",
                wallet_id=agent_wallet_id,
                tool=ACP_CHECKOUT_TOOL,
                endpoint=ACP_CHECKOUT_ENDPOINT,
                key_id=key_id,
                request_id=_audit_request_id(order_id),
                ok=True,
                metadata={
                    "order_id": order_id,
                    "intent_id": request.intent_id,
                    "merchant_domain": request.merchant_domain,
                    "derived_total_minor": total_minor,
                    "derived_total": derived_total,
                    "currency": currency,
                    "credits": str(credits),
                    "permit_id": permit.permit_id,
                    "stripe_payment_intent_id": charge.get("payment_intent_id"),
                },
            )

            # 8. Signed receipt; ledger_entry_id is None because no real
            # ledger entry exists (the adapter never mints or debits
            # credits). The idempotency record link makes the receipt itself
            # replay-safe.
            receipt = await get_receipt_service().create_receipt(
                permit_id=permit.permit_id,
                wallet_id=agent_wallet_id,
                key_id=key_id,
                tool=ACP_CHECKOUT_TOOL,
                request_payload={
                    "intent_id": request.intent_id,
                    "merchant_domain": request.merchant_domain,
                    "line_items_digest": line_items_digest(request.line_items),
                    "client_total": request.client_total,
                },
                response_payload={
                    "order_id": order_id,
                    "stripe_payment_intent_id": charge.get("payment_intent_id"),
                    "payment_status": charge.get("status"),
                    "derived_total": derived_total,
                    "currency": currency,
                },
                ledger_entry_id=None,
                credits_authorized=credits,
                credits_charged=credits,
                outcome="success",
                audit_event_id=event.event_id,
                idempotency_record_id=begun.record_id,
            )

        except ACPBridgeError:
            await _rollback()
            raise
        except Exception as exc:
            await _rollback()
            raise ACPBridgeError("acp_settlement_record_failed") from exc

        response = ACPCheckoutResponse(
            order_id=order_id,
            intent_id=request.intent_id,
            permit_id=permit.permit_id,
            receipt_id=receipt.receipt_id,
            audit_event_id=event.event_id,
            derived_total=derived_total,
            status="settled",
        )
        # 9. Complete the intent's idempotency record so a replayed intent_id
        # returns this exact result without charging again. Deliberately
        # outside the rollback guard: once the charge, audit event, and
        # receipt exist the checkout IS settled, and releasing the budget
        # over a bookkeeping failure here would fabricate un-settled state.
        await idem.complete(
            wallet_id=agent_wallet_id,
            endpoint=ACP_CHECKOUT_ENDPOINT,
            idempotency_key=request.intent_id,
            response_reference=receipt.receipt_id,
            response_json=response.model_dump(mode="json"),
            status_code=200,
        )
        return response


_adapter: ACPCommerceAdapter | None = None


def get_acp_commerce_adapter() -> ACPCommerceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = ACPCommerceAdapter()
    return _adapter
