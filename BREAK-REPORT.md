# Break Report: billing charge and top-up paths

Target: app/services/billing_engine.py and app/routers/billing.py (plus the
Stripe top-up settlement path they depend on). All testing used local test
setups and Stripe SDK test doubles only. No live Stripe, no production
charging, no production data touched.

## Summary

Probed 5 assigned scenarios plus boundary extras: missing idempotency on
retry, concurrent double-charge races, mid-way Stripe stub failures, charges
against empty wallets, and charges after key revocation.

Result: 2 real breaks found, both fixed and tested. 6 of 8 new regression
tests fail on the old code and pass on the new code (the other 2 are
boundary and fail-closed guards that pass on both). 0 fixed-but-failing, 0
blocked. 1 finding needs Chris's decision (opt-in idempotency means a
keyless retry still bills twice; fixing that is a breaking API change).

Verified intact (no break): concurrent charges never overdraw (30 racing
charges settled to exactly the balance, losers got 402), empty wallet
answers 402 with correct shortfall, exact-balance charge succeeds, revoked
API keys are refused with 403, infinite units are refused with 422 at HTTP
and ValueError in the engine, and a Stripe outage during top-up prepare
fails closed with nothing minted.

## Finding 1 (high): dust charges meter service for free

What broke: POST /v1/billing/charge with tiny units (for example
platform_fee at units=1e-9, a charge of 1E-10 credits) answered 200. The
balance did not move (10.0 stayed 10.0) and the ledger stored a zero-value
debit row (Decimal -0E-8). Any caller able to reach the charge path with
sub-precision amounts gets metered service without paying, and the ledger
fills with zero rows.

How to reproduce: create a funded sponsor wallet, then charge
service=platform_fee units=1e-9. Old code returns 200 with amount -1e-10
and balance_after equal to the starting balance.

Root cause: app/services/billing_engine.py, charge() computed
`charge_amount = units * credits_per_unit` with no floor, while balances
and ledger amounts persist at 8 decimal places, so anything under 1E-8
rounds to zero on write.

Fix: app/services/billing_engine.py:89 defines MINIMUM_CHARGE_AMOUNT
(0.00000001); charge() raises ValueError for a real (non-dry-run) debit
below it, and app/routers/billing.py:840 maps that to 400 invalid_charge
with a governance record and idempotency completion, instead of the 500 an
uncaught ValueError used to produce. Dry-run estimates still answer for
tiny amounts. On the governed MCP path the ValueError propagates before
any write, so reconciliation finds no debit and fails closed with no
dispatch.

Test results: tests/test_billing_adversarial.py covers HTTP refusal,
engine refusal, the exact 1E-8 boundary still debiting, and dry-run still
estimating. All fail on old code except the boundary guard, all pass on
new code. Suites run green: test_billing, test_stripe_integration,
test_wallet_ledger_integrity, test_billing_boundary_regressions,
test_mcp_upstream_governed, test_swarm_wallets, test_arbitrage_regressions.

## Finding 2 (medium): Stripe payment-failed handler crashed on malformed payloads

What broke: calling the payment_intent.payment_failed handler with a
payload missing `metadata` raised KeyError, with
`"last_payment_error": null` raised AttributeError, and with a non-object
body raised TypeError. End to end, POST /v1/webhooks/stripe for such an
event answered 500, which Stripe retries indefinitely, while the payment
failure alert the handler exists to send never went out.

How to reproduce: post a payment_intent.payment_failed event whose object
is `{"id": "pi_x"}` (no metadata) to /v1/webhooks/stripe with the Stripe
construct_event call stubbed. Old code returns 500.

Root cause: app/services/stripe_integration.py:398, `_handle_payment_failed`
indexed `payment_intent["metadata"]` directly and chained
`.get("last_payment_error", {}).get(...)` with no null guard.

Fix: the handler now reads every field through the existing `_stripe_value`
accessor with defaults (unknown ids become "unknown", missing errors become
"Unknown error"), logs and drops payloads with nothing usable, and only
notifies when a real wallet id string is present.

Test results: tests/test_billing_adversarial.py covers all three malformed
shapes plus the end-to-end 200. All fail on old code, all pass on new code.

## Verified intact, no change made

- Double-charge race: 30 concurrent 1.0-credit charges against a 10.0
  balance produced exactly 10 debits, balance exactly 0, 20 denials, no
  5xx. The guarded debit already holds.
- Keyed retry replays one debit; unkeyed retry bills twice (see open
  question below).
- Empty wallet: 402 insufficient_funds, balance untouched, no debit row.
- Revoked key: charge before revoke 200, revoke 204, charge after 403
  invalid_api_key.
- Top-up prepare with the Stripe SDK stubbed to raise: 400
  topup_prepare_error, balance unchanged, no new ledger entries.
- Webhook succeeded with tampered credit metadata still rejected as
  invalid settlement (existing validation, unchanged).

## Open questions

1. Keyless charge retries still bill twice, by design: idempotency on
   POST /v1/billing/charge is opt-in via the Idempotency-Key header, so the
   server cannot tell a retry from a new charge. Requiring the header would
   be a breaking API change and needs Chris's call. No code changed here.
2. Stripe retries any non-2xx webhook response, including 400s for
   genuinely invalid settlements (for example a refund naming an unknown
   payment intent). Harmless because all handlers are idempotent, but noisy
   under a misconfigured sender. Left as is.
3. The `.venv` symlink at the worktree root shows as untracked; it was
   already there at session start and was not touched.
