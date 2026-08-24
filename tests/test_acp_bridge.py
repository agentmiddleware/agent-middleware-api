"""Tests for the ACP commerce bridge (WP2).

Covers the governed checkout loop end-to-end (permit v2 bounds, receipt,
audit-chain binding), intent-id idempotency (no double charge), the
client-total exact-equality gate, negative/malformed-input paths, tenant
isolation, SPT mid-flow failure atomicity (budget released, no receipt), the
never-persist-the-token invariant, and a median-latency acceptance bound.

The module stem is in tests/conftest.py's DORMANT_SURFACE_TEST_MODULES, so the
billing expansion routes are mounted automatically for these tests.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.acp import ACPCheckoutRequest
from app.services.acp_bridge import (
    ACP_CHECKOUT_ENDPOINT,
    ACPBridgeError,
    get_acp_commerce_adapter,
    translate_to_permit_bounds,
)
from app.services.audit_log import list_audit_events
from app.services.idempotency import IdempotencyService, get_idempotency_service
from app.services.permits import get_permit_service
from app.services.receipts import get_receipt_service
from app.services.signing_keys import sha256_hex
from app.services.stripe_integration import StripeIntegration
from tests.test_trust_helpers import provision_agent_wallet

# A recognizable sentinel: every leak assertion scans persisted artifacts for
# this exact string.
SPT_TOKEN = "spt_test_secret_token_do_not_leak"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def spt_stub(monkeypatch):
    """Stub the outbound SPT charge; records every call it receives."""
    calls: list[dict[str, Any]] = []

    async def _fake_charge(
        self, *, spt_token, amount_minor, currency, idempotency_key
    ):
        calls.append(
            {
                "spt_token": spt_token,
                "amount_minor": amount_minor,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return {
            "payment_intent_id": f"pi_acp_{len(calls)}",
            "status": "succeeded",
            "amount": amount_minor,
            "currency": currency,
        }

    monkeypatch.setattr(
        StripeIntegration, "charge_shared_payment_token", _fake_charge
    )
    return calls


def checkout_body(
    intent_id: str,
    *,
    client_total: int = 50,
    quantity: int = 2,
    unit_amount: int = 25,
    currency: str = "usd",
    merchant_domain: str = "merchant.example.com",
) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "line_items": [
            {
                "name": "Widget",
                "sku": "W-1",
                "quantity": quantity,
                "unit_amount": unit_amount,
                "currency": currency,
            }
        ],
        "spt_token": SPT_TOKEN,
        "merchant_domain": merchant_domain,
        "client_total": client_total,
    }


def checkout_url(ctx: dict[str, Any]) -> str:
    return (
        "/v1/billing/acp/checkout"
        f"?sponsor_wallet_id={ctx['sponsor_wallet_id']}"
        f"&agent_wallet_id={ctx['agent_wallet_id']}"
    )


def test_translate_to_permit_bounds_is_pure_and_exact():
    request = ACPCheckoutRequest(
        intent_id="intent-translate-1",
        line_items=[
            {
                "name": "Widget",
                "sku": "W-1",
                "quantity": 2,
                "unit_amount": 25,
                "currency": "usd",
            },
            {
                "name": "Gadget",
                "quantity": 3,
                "unit_amount": 100,
                "currency": "usd",
            },
        ],
        spt_token="tok",
        merchant_domain="shop.example.com",
        client_total=350,
    )
    bounds = translate_to_permit_bounds(
        request,
        sponsor_wallet_id="spn-test",
        agent_wallet_id="agt-test",
        key_id="key-test",
    )
    # 350 cents at the default 1000 credits/$ rate.
    assert bounds.max_credits == Decimal("3500")
    assert bounds.aggregate_value_cap == Decimal("3500")
    assert bounds.allowed_tools == ["acp.checkout"]
    assert bounds.max_calls_per_tool == {"acp.checkout": 1}
    assert bounds.recipient_domain == "shop.example.com"
    assert bounds.issuer_wallet_id == "spn-test"
    assert bounds.subject_wallet_id == "agt-test"
    assert bounds.subject_key_id == "key-test"
    assert bounds.forbidden_fields == []


@pytest.mark.anyio
async def test_acp_checkout_end_to_end(client, spt_stub, clean_database):
    ctx = await provision_agent_wallet(client)
    resp = await client.post(
        checkout_url(ctx),
        json=checkout_body("intent-e2e-1"),
        headers=ctx["agent_headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["order_id"] == "acp-intent-e2e-1"
    assert data["intent_id"] == "intent-e2e-1"
    assert data["status"] == "settled"
    # Exact string: 50 cents must render as "0.50", never "0.5".
    assert data["derived_total"] == "0.50"

    # Exactly one outbound charge, with the server-derived amount and the
    # order-derived Stripe idempotency key.
    assert len(spt_stub) == 1
    assert spt_stub[0]["amount_minor"] == 50
    assert spt_stub[0]["currency"] == "usd"
    assert spt_stub[0]["idempotency_key"] == "acp-intent-e2e-1"

    # The permit carries the exact v2 bounds the checkout was translated to.
    permit = await get_permit_service().get_permit(data["permit_id"])
    assert permit is not None
    assert permit.issuer_wallet_id == ctx["sponsor_wallet_id"]
    assert permit.subject_wallet_id == ctx["agent_wallet_id"]
    assert permit.subject_key_id == ctx["key_id"]
    assert permit.allowed_tools == ["acp.checkout"]
    assert permit.max_credits == Decimal("500")
    assert permit.max_calls_per_tool == {"acp.checkout": 1}
    assert permit.aggregate_value_cap == Decimal("500")
    assert permit.recipient_domain == "merchant.example.com"
    # The reservation consumed the whole single-use budget.
    assert permit.spent_credits == Decimal("500")

    # The receipt exists and its Ed25519 signature verifies.
    verify = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": data["receipt_id"]},
        headers=ctx["agent_headers"],
    )
    assert verify.status_code == 200, verify.text
    verdict = verify.json()
    assert verdict["valid"] is True
    receipt = verdict["receipt"]
    assert receipt["permit_id"] == data["permit_id"]
    assert receipt["tool"] == "acp.checkout"
    assert receipt["outcome"] == "success"
    assert receipt["audit_event_id"] == data["audit_event_id"]
    assert Decimal(receipt["credits_charged"]) == Decimal("500")
    assert receipt["ledger_entry_id"] is None  # no real ledger writes

    # The order id is bound into a chained audit event, and the router's
    # governance event is indexed under the SAME request key — one checkout,
    # one request_id across governance and settlement evidence.
    events = await list_audit_events(request_id=data["order_id"])
    assert {e.event for e in events} == {
        "acp_checkout_settled",
        "billing.acp_checkout",
    }
    settled_events = [e for e in events if e.event == "acp_checkout_settled"]
    assert len(settled_events) == 1
    event = settled_events[0]
    assert event.event_id == data["audit_event_id"]
    assert event.wallet_id == ctx["agent_wallet_id"]
    assert event.tool == "acp.checkout"
    assert event.metadata["order_id"] == data["order_id"]
    assert event.metadata["intent_id"] == "intent-e2e-1"
    assert event.metadata["merchant_domain"] == "merchant.example.com"
    assert event.metadata["stripe_payment_intent_id"] == "pi_acp_1"
    assert Decimal(event.metadata["credits"]) == Decimal("500")
    assert event.metadata["permit_id"] == data["permit_id"]

    # ...and the wallet's tamper-evident chain verifies end to end.
    chain = await client.post(
        "/v1/audit/verify-chain", json={}, headers=ctx["agent_headers"]
    )
    assert chain.status_code == 200
    chain_verdict = chain.json()
    assert chain_verdict["valid"] is True, chain_verdict
    assert chain_verdict["checked_events"] >= 1


@pytest.mark.anyio
async def test_acp_checkout_end_to_end_under_45ms(client, spt_stub, clean_database):
    """Median service-level checkout latency stays under 45ms (SPT stubbed)."""
    ctx = await provision_agent_wallet(client)
    adapter = get_acp_commerce_adapter()

    def make_request(intent_id: str) -> ACPCheckoutRequest:
        return ACPCheckoutRequest(**checkout_body(intent_id))

    async def run(intent_id: str):
        return await adapter.execute_checkout(
            make_request(intent_id),
            sponsor_wallet_id=ctx["sponsor_wallet_id"],
            agent_wallet_id=ctx["agent_wallet_id"],
            key_id=ctx["key_id"],
        )

    # One warm-up so first-use costs (key publication, connection setup) do
    # not land in the measured samples.
    await run("intent-perf-warmup")

    samples: list[float] = []
    for index in range(10):
        started = time.perf_counter()
        result = await run(f"intent-perf-{index}")
        samples.append(time.perf_counter() - started)
        assert result.status == "settled"

    # Median rather than max: a single noisy CI scheduling blip must not
    # flake the suite, but the typical checkout must stay fast. The bound is
    # env-overridable so a slow runner can widen it without editing code.
    budget_s = float(os.environ.get("ACP_CHECKOUT_MEDIAN_BUDGET_S", "0.045"))
    assert statistics.median(samples) < budget_s, samples


@pytest.mark.anyio
async def test_acp_duplicate_intent_id_does_not_double_charge(
    client, spt_stub, clean_database
):
    ctx = await provision_agent_wallet(client)
    body = checkout_body("intent-dup-1")

    first = await client.post(
        checkout_url(ctx), json=body, headers=ctx["agent_headers"]
    )
    assert first.status_code == 201, first.text
    first_data = first.json()
    permit_before = await get_permit_service().get_permit(first_data["permit_id"])
    assert permit_before is not None

    second = await client.post(
        checkout_url(ctx), json=body, headers=ctx["agent_headers"]
    )
    assert second.status_code == 201, second.text
    second_data = second.json()

    # The replay returns the ORIGINAL checkout result in full.
    assert second_data["order_id"] == first_data["order_id"]
    assert second_data["permit_id"] == first_data["permit_id"]
    assert second_data["receipt_id"] == first_data["receipt_id"]
    assert second_data["audit_event_id"] == first_data["audit_event_id"]

    # The SPT rail was hit exactly once, no second permit budget was
    # consumed, and no second receipt exists.
    assert len(spt_stub) == 1
    permit_after = await get_permit_service().get_permit(first_data["permit_id"])
    assert permit_after is not None
    assert permit_after.spent_credits == permit_before.spent_credits
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 1


@pytest.mark.anyio
async def test_acp_same_intent_different_body_is_rejected(
    client, spt_stub, clean_database
):
    """Reusing a settled intent id with a different cart is a 409 conflict —
    the original checkout is neither replayed for the new body nor
    re-charged."""
    ctx = await provision_agent_wallet(client)
    first = await client.post(
        checkout_url(ctx),
        json=checkout_body("intent-conflict-1"),
        headers=ctx["agent_headers"],
    )
    assert first.status_code == 201, first.text
    assert len(spt_stub) == 1

    # Same intent id, larger cart: the idempotency request hash differs.
    conflicting = checkout_body("intent-conflict-1", quantity=3, client_total=75)
    second = await client.post(
        checkout_url(ctx), json=conflicting, headers=ctx["agent_headers"]
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["error"] == "acp_intent_conflict"

    # The settlement rail was hit exactly once, by the original checkout.
    assert len(spt_stub) == 1


@pytest.mark.anyio
async def test_acp_client_total_mismatch_rejected(client, spt_stub, clean_database):
    ctx = await provision_agent_wallet(client)
    # Off by one cent from the derived 50: must be refused outright.
    resp = await client.post(
        checkout_url(ctx),
        json=checkout_body("intent-mismatch-1", client_total=51),
        headers=ctx["agent_headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "acp_total_mismatch"

    # Nothing happened: no Stripe call, no permit, no receipt.
    assert spt_stub == []
    _, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 0
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 0


@pytest.mark.anyio
async def test_acp_checkout_exceeding_wallet_balance_rejected(
    client, spt_stub, clean_database
):
    """A derived total beyond the agent wallet's balance is refused before
    any permit is minted or the settlement rail is touched."""
    ctx = await provision_agent_wallet(client)
    # provision_agent_wallet funds the agent wallet with 1000 budget credits
    # = 100 cents at the default 1000 credits/$ rate; 101 cents overruns it.
    body = checkout_body(
        "intent-overrun-1", quantity=1, unit_amount=101, client_total=101
    )
    resp = await client.post(
        checkout_url(ctx), json=body, headers=ctx["agent_headers"]
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error"] == "permit_budget_exceeds_wallet_balance"

    # Nothing moved: no Stripe call, no permit reserved.
    assert spt_stub == []
    _, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 0


@pytest.mark.anyio
async def test_acp_rejects_malformed_checkouts(client, spt_stub, clean_database):
    ctx = await provision_agent_wallet(client)
    url = checkout_url(ctx)
    headers = ctx["agent_headers"]

    empty_items = checkout_body("intent-bad-empty")
    empty_items["line_items"] = []
    bad_intent = checkout_body("intent-bad-id")
    bad_intent["intent_id"] = "bad intent id!"
    malformed = [
        ("empty line_items", empty_items),
        ("zero quantity", checkout_body("intent-bad-q0", quantity=0)),
        ("negative quantity", checkout_body("intent-bad-qneg", quantity=-1)),
        (
            "negative unit_amount",
            checkout_body("intent-bad-amt", unit_amount=-5),
        ),
        ("unsupported currency", checkout_body("intent-bad-eur", currency="eur")),
        (
            "uppercase currency not folded",
            checkout_body("intent-bad-usd-upper", currency="USD"),
        ),
        (
            "domain with spaces",
            checkout_body("intent-bad-dom1", merchant_domain="not a domain!"),
        ),
        (
            "domain with scheme",
            checkout_body(
                "intent-bad-dom2",
                merchant_domain="https://merchant.example.com",
            ),
        ),
        (
            "single-label domain",
            checkout_body("intent-bad-dom3", merchant_domain="localhost"),
        ),
        (
            "leading-hyphen label",
            checkout_body("intent-bad-dom4", merchant_domain="-bad.example.com"),
        ),
        ("malformed intent id", bad_intent),
    ]
    for label, body in malformed:
        resp = await client.post(url, json=body, headers=headers)
        assert resp.status_code == 422, f"{label}: {resp.status_code} {resp.text}"

    # No malformed input reached the settlement rail or minted anything.
    assert spt_stub == []
    _, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 0


@pytest.mark.anyio
async def test_acp_unauthorized_caller_rejected(client, spt_stub, clean_database):
    victim = await provision_agent_wallet(client)
    attacker = await provision_agent_wallet(client)

    # A wallet-scoped key from another tenant cannot check out against the
    # victim's agent wallet.
    resp = await client.post(
        checkout_url(victim),
        json=checkout_body("intent-auth-1"),
        headers=attacker["agent_headers"],
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "wallet_access_denied"

    # A key that does own the agent wallet still cannot attribute permit
    # issuance to a sponsor that does not fund it.
    cross_sponsor_url = (
        "/v1/billing/acp/checkout"
        f"?sponsor_wallet_id={attacker['sponsor_wallet_id']}"
        f"&agent_wallet_id={victim['agent_wallet_id']}"
    )
    resp = await client.post(
        cross_sponsor_url,
        json=checkout_body("intent-auth-2"),
        headers=victim["agent_headers"],
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "sponsor_wallet_access_denied"

    assert spt_stub == []
    _, permits_total = await get_permit_service().list_permits(
        wallet_id=victim["agent_wallet_id"]
    )
    assert permits_total == 0
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=victim["agent_wallet_id"]
    )
    assert receipts_total == 0


@pytest.mark.anyio
async def test_acp_spt_failure_releases_budget_and_persists_no_receipt(
    client, monkeypatch, clean_database
):
    ctx = await provision_agent_wallet(client)

    calls: list[str] = []

    async def _flaky_charge(
        self, *, spt_token, amount_minor, currency, idempotency_key
    ):
        calls.append(idempotency_key)
        if len(calls) == 1:
            raise RuntimeError("stripe unreachable")
        return {
            "payment_intent_id": "pi_acp_retry",
            "status": "succeeded",
            "amount": amount_minor,
            "currency": currency,
        }

    monkeypatch.setattr(
        StripeIntegration, "charge_shared_payment_token", _flaky_charge
    )

    body = checkout_body("intent-fail-1")
    resp = await client.post(
        checkout_url(ctx), json=body, headers=ctx["agent_headers"]
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "acp_spt_charge_failed"

    # Atomicity: the reservation was released on the minted permit and no
    # receipt was persisted.
    permits, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 1
    assert permits[0].spent_credits == Decimal("0")
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 0

    # The failed attempt freed the intent id: a retry settles normally.
    retry = await client.post(
        checkout_url(ctx), json=body, headers=ctx["agent_headers"]
    )
    assert retry.status_code == 201, retry.text
    assert len(calls) == 2
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 1


@pytest.mark.anyio
async def test_acp_unsettled_stripe_status_is_a_failure(
    client, monkeypatch, clean_database
):
    ctx = await provision_agent_wallet(client)

    async def _pending_charge(
        self, *, spt_token, amount_minor, currency, idempotency_key
    ):
        return {
            "payment_intent_id": "pi_acp_pending",
            "status": "requires_action",
            "amount": amount_minor,
            "currency": currency,
        }

    monkeypatch.setattr(
        StripeIntegration, "charge_shared_payment_token", _pending_charge
    )

    resp = await client.post(
        checkout_url(ctx),
        json=checkout_body("intent-pending-1"),
        headers=ctx["agent_headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "acp_spt_charge_failed"

    permits, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 1
    assert permits[0].spent_credits == Decimal("0")
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 0

    # Uniform rule: every rollback after the charge attempt leaves evidence —
    # a definitively non-settled status included, since Stripe may still hold
    # a resolvable PaymentIntent under the recorded idempotency key.
    events = await list_audit_events(request_id="acp-intent-pending-1")
    failures = [e for e in events if e.event == "acp_checkout_charge_failed"]
    assert len(failures) == 1
    assert failures[0].ok is False
    assert (
        failures[0].metadata["stripe_idempotency_key"] == "acp-intent-pending-1"
    )


@pytest.mark.anyio
async def test_acp_ambiguous_charge_failure_leaves_audit_evidence(
    client, monkeypatch, clean_database
):
    """A transport-style failure (timeout/connection reset) after the charge
    was dispatched may hide money Stripe actually captured. The rollback must
    still append an ok=False audit event carrying the Stripe idempotency key,
    so an orphaned charge is always discoverable from the audit chain."""
    ctx = await provision_agent_wallet(client)

    async def _transport_failure(
        self, *, spt_token, amount_minor, currency, idempotency_key
    ):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(
        StripeIntegration, "charge_shared_payment_token", _transport_failure
    )

    resp = await client.post(
        checkout_url(ctx),
        json=checkout_body("intent-ambiguous-1"),
        headers=ctx["agent_headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "acp_spt_charge_failed"

    # The reservation was released and no receipt exists...
    permits, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 1
    assert permits[0].spent_credits == Decimal("0")
    _, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 0

    # ...but the failure is durable evidence, indexed under the SAME request
    # key a settlement would use and carrying everything needed to find a
    # possibly-orphaned Stripe charge — never the token.
    events = await list_audit_events(request_id="acp-intent-ambiguous-1")
    failures = [e for e in events if e.event == "acp_checkout_charge_failed"]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.ok is False
    assert failure.wallet_id == ctx["agent_wallet_id"]
    assert failure.tool == "acp.checkout"
    assert failure.metadata["order_id"] == "acp-intent-ambiguous-1"
    assert failure.metadata["intent_id"] == "intent-ambiguous-1"
    assert failure.metadata["merchant_domain"] == "merchant.example.com"
    assert failure.metadata["derived_total_minor"] == 50
    assert failure.metadata["currency"] == "usd"
    assert failure.metadata["stripe_idempotency_key"] == "acp-intent-ambiguous-1"
    assert failure.metadata["failure"] == "RuntimeError"
    assert SPT_TOKEN not in json.dumps(failure.metadata, default=str)


@pytest.mark.anyio
async def test_charge_shared_payment_token_runs_stripe_io_off_the_event_loop(
    monkeypatch,
):
    """The real charge helper must offload the sync Stripe SDK call to a
    worker thread instead of blocking the event loop."""
    seen: dict[str, Any] = {}

    def _sync_create(**kwargs):
        seen["thread"] = threading.current_thread()
        seen["kwargs"] = kwargs
        return {
            "id": "pi_offload_1",
            "status": "succeeded",
            "amount": kwargs["amount"],
            "currency": kwargs["currency"],
        }

    monkeypatch.setattr(
        "app.services.stripe_integration.stripe.PaymentIntent.create",
        _sync_create,
    )

    result = await StripeIntegration().charge_shared_payment_token(
        spt_token="tok_offload",
        amount_minor=50,
        currency="usd",
        idempotency_key="acp-intent-offload-1",
    )

    assert result == {
        "payment_intent_id": "pi_offload_1",
        "status": "succeeded",
        "amount": 50,
        "currency": "usd",
    }
    # Idempotency-key passthrough semantics are unchanged by the offload.
    assert seen["kwargs"]["idempotency_key"] == "acp-intent-offload-1"
    assert seen["kwargs"]["payment_method"] == "tok_offload"
    # The sync Stripe call ran on a worker thread, not the loop's thread.
    assert seen["thread"] is not threading.current_thread()


@pytest.mark.anyio
async def test_acp_spt_token_never_persisted(client, spt_stub, clean_database):
    ctx = await provision_agent_wallet(client)
    resp = await client.post(
        checkout_url(ctx),
        json=checkout_body("intent-secret-1"),
        headers=ctx["agent_headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # The checkout response itself.
    assert SPT_TOKEN not in resp.text

    # The stored receipt (payload hashes and every field it exposes).
    receipt_resp = await client.get(
        f"/v1/receipts/{data['receipt_id']}", headers=ctx["agent_headers"]
    )
    assert receipt_resp.status_code == 200
    assert SPT_TOKEN not in receipt_resp.text

    # Every audit event on the wallet's chain, the settled event included —
    # metadata is inside the signed payload, so a token here would be
    # permanent.
    events = await list_audit_events(
        wallet_id=ctx["agent_wallet_id"], limit=200
    )
    settled = [e for e in events if e.event == "acp_checkout_settled"]
    assert len(settled) == 1
    for event in events:
        assert SPT_TOKEN not in json.dumps(event.metadata, default=str)

    # The durable idempotency record's stored response.
    record = await get_idempotency_service().get_record(
        wallet_id=ctx["agent_wallet_id"],
        endpoint=ACP_CHECKOUT_ENDPOINT,
        idempotency_key="intent-secret-1",
    )
    assert record is not None
    assert record.response_json is not None
    assert SPT_TOKEN not in record.response_json

    # The stored request identity must be the hash of the SANITIZED payload:
    # rebuild it independently with the bridge's own payload builder and the
    # exact hashing begin_with_record applies (sha256_hex over the dict). Any
    # future change that starts folding the token into the hashed payload
    # changes the digest and fails here.
    sanitized_payload = get_acp_commerce_adapter()._idempotency_payload(
        ACPCheckoutRequest.model_validate(checkout_body("intent-secret-1")),
        sponsor_wallet_id=ctx["sponsor_wallet_id"],
        agent_wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
    )
    assert SPT_TOKEN not in json.dumps(sanitized_payload, default=str)
    assert record.request_hash == sha256_hex(sanitized_payload)


async def _backdate_intent_record(intent_id: str, *, wallet_id: str) -> None:
    """Age one wallet's intent record past the staleness threshold.

    Constrained by the full idempotency identity (wallet, endpoint, key) so
    two wallets reusing an intent id can never make ``scalar_one`` ambiguous.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from app.core.time import utc_now
    from app.db.database import get_session_factory
    from app.db.models import IdempotencyRecordModel
    from app.services.acp_bridge import _INTENT_STALE_SECONDS

    factory = get_session_factory()
    async with factory() as session:
        record = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.wallet_id == wallet_id,
                    IdempotencyRecordModel.endpoint == ACP_CHECKOUT_ENDPOINT,
                    IdempotencyRecordModel.idempotency_key == intent_id,
                )
            )
        ).scalar_one()
        assert record.response_json is None  # crashed before completion
        record.created_at = utc_now() - timedelta(seconds=_INTENT_STALE_SECONDS + 1)
        session.add(record)
        await session.commit()


@pytest.fixture
async def crash_recovery_ctx(client, clean_database):
    """Shared setup for the stale-crashed-intent recovery tests: a funded
    wallet, the adapter, and the checkout kwargs. A process that dies
    mid-finalization leaves the intent's record in progress with no repair
    path of its own; each recovery test induces one crash shape on top of
    this context with its own isolated patches."""
    ctx = await provision_agent_wallet(client)
    return {
        "ctx": ctx,
        "adapter": get_acp_commerce_adapter(),
        "kwargs": {
            "sponsor_wallet_id": ctx["sponsor_wallet_id"],
            "agent_wallet_id": ctx["agent_wallet_id"],
            "key_id": ctx["key_id"],
        },
    }


@pytest.mark.anyio
async def test_acp_stale_intent_crashed_after_receipt_recovers_from_receipt(
    spt_stub, monkeypatch, crash_recovery_ctx
):
    """Crash shape 1: death between the receipt write and idem.complete. The
    settlement is durable, so once the record goes stale it is completed FROM
    the receipt with zero re-execution — and the original crash surfaces
    unwrapped, with the budget reservation intact."""
    ctx = crash_recovery_ctx["ctx"]
    adapter = crash_recovery_ctx["adapter"]
    kwargs = crash_recovery_ctx["kwargs"]
    request = ACPCheckoutRequest.model_validate(checkout_body("intent-crash-1"))

    original_complete = IdempotencyService.complete

    async def _crash_complete(self, **complete_kwargs):
        raise RuntimeError("induced crash before idem.complete")

    monkeypatch.setattr(IdempotencyService, "complete", _crash_complete)
    # idem.complete runs OUTSIDE the settlement rollback guard: once the
    # charge, audit event, and receipt are durable the checkout IS settled,
    # so the induced error must surface as itself — not re-labeled a
    # settlement-record failure.
    with pytest.raises(RuntimeError) as crash:
        await adapter.execute_checkout(request, **kwargs)
    assert not isinstance(crash.value, ACPBridgeError)
    assert len(spt_stub) == 1  # the charge itself succeeded

    # The budget reservation SURVIVED: the charge is durable, so the
    # rollback (release + abandon) must not have run.
    permits, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 1
    assert permits[0].spent_credits == Decimal("500")

    # Restore the real complete so recovery can finish the record.
    monkeypatch.setattr(IdempotencyService, "complete", original_complete)

    # Fresh record = possibly a live concurrent attempt: still refused.
    with pytest.raises(ACPBridgeError) as blocked:
        await adapter.execute_checkout(request, **kwargs)
    assert blocked.value.reason == "acp_intent_in_progress"
    assert len(spt_stub) == 1

    await _backdate_intent_record(
        "intent-crash-1", wallet_id=ctx["agent_wallet_id"]
    )

    # Recovery completes the record from the durable receipt: NO re-charge,
    # NO re-execution — the original settlement's identifiers come back.
    receipts_before, _ = await get_receipt_service().list_receipts()
    settled = await adapter.execute_checkout(request, **kwargs)
    assert settled.order_id == "acp-intent-crash-1"
    assert settled.status == "settled"
    assert settled.derived_total == "0.50"
    assert len(spt_stub) == 1
    receipts_after, _ = await get_receipt_service().list_receipts()
    assert len(receipts_after) == len(receipts_before)
    assert settled.receipt_id in {r.receipt_id for r in receipts_after}

    # The recovered intent now replays like any settled one.
    replay = await adapter.execute_checkout(request, **kwargs)
    assert replay == settled
    assert len(spt_stub) == 1


@pytest.mark.anyio
async def test_acp_stale_intent_crashed_before_receipt_reruns_without_double_charge(
    spt_stub, monkeypatch, crash_recovery_ctx
):
    """Crash shape 2: hard death after the charge but before the receipt. A
    BaseException models a killed process: the adapter's rollback guard
    (except Exception) never runs, so the reservation and record stay put.
    Once stale, the receiptless record is abandoned and the checkout re-runs;
    Stripe-side idempotency (key = deterministic order_id) guarantees the
    re-executed charge is the original one, not a second (settlement-rails
    checklist item 7)."""
    import app.services.acp_bridge as acp_module

    ctx = crash_recovery_ctx["ctx"]
    adapter = crash_recovery_ctx["adapter"]
    kwargs = crash_recovery_ctx["kwargs"]
    request = ACPCheckoutRequest.model_validate(checkout_body("intent-crash-2"))

    original_audit = acp_module.record_audit_event

    async def _hard_death(**audit_kwargs):
        raise KeyboardInterrupt("induced hard death before the receipt")

    monkeypatch.setattr(acp_module, "record_audit_event", _hard_death)
    with pytest.raises(KeyboardInterrupt):
        await adapter.execute_checkout(request, **kwargs)
    assert len(spt_stub) == 1  # the charge went through once

    # Restore the real audit writer so the recovery re-run can settle.
    monkeypatch.setattr(acp_module, "record_audit_event", original_audit)

    await _backdate_intent_record(
        "intent-crash-2", wallet_id=ctx["agent_wallet_id"]
    )

    # Recovery abandons the receiptless record and re-runs the checkout; the
    # re-executed charge carries the SAME Stripe idempotency key, so Stripe
    # returns the original PaymentIntent — one customer charge, not two.
    settled = await adapter.execute_checkout(request, **kwargs)
    assert settled.order_id == "acp-intent-crash-2"
    assert settled.status == "settled"
    assert len(spt_stub) == 2
    assert spt_stub[0]["idempotency_key"] == spt_stub[1]["idempotency_key"]

    # Exactly ONE settlement artifact set exists for the recovered intent...
    receipts, receipts_total = await get_receipt_service().list_receipts(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert receipts_total == 1
    assert receipts[0].receipt_id == settled.receipt_id
    assert receipts[0].permit_id == settled.permit_id

    # ...while the crashed attempt's permit is orphaned (left to expire for
    # the budget sweep), never reused: the re-run minted a fresh one.
    permits, permits_total = await get_permit_service().list_permits(
        wallet_id=ctx["agent_wallet_id"]
    )
    assert permits_total == 2
    assert settled.permit_id in {p.permit_id for p in permits}
    orphaned = [p for p in permits if p.permit_id != settled.permit_id]
    assert len(orphaned) == 1

    # The chain marks this two-permits-one-receipt shape as crash recovery,
    # indexed under the same request key as the settlement itself.
    events = await list_audit_events(request_id="acp-intent-crash-2")
    recovered = [e for e in events if e.event == "acp_intent_recovered"]
    assert len(recovered) == 1
    assert recovered[0].ok is True
    assert recovered[0].metadata["intent_id"] == "intent-crash-2"
    assert recovered[0].metadata["abandoned_record_id"]
