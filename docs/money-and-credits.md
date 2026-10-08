# Money and credits: what you pay for and what you do not

A credit is a closed-loop metering unit for the pilot on an
operator-provisioned wallet, not payment rails. The gateway reserves credits
before a governed call runs and records the debit on an internal ledger with a
signed receipt. Credits never leave this system and cannot be paid out.

## How credits come into existence

Exactly two paths create credits:

1. **Verified Stripe top-up, where configured.** A one-off card payment
   settles through Stripe, a signature-verified webhook confirms the settled
   amount, and the gateway mints matching credits to a sponsor wallet.
   Credits are derived from the settled amount Stripe reports, never from
   amounts a client asserts.
2. **Operator issuance.** A bootstrap admin funds a sponsor wallet directly.
   This is the operator's manual funding path and the fallback when Stripe is
   not configured.

There is no other way to create credits. Agent wallets are funded by transfer
from their sponsor, not by direct top-up.

## What Stripe covers today

- One-off top-ups only, in USD, to sponsor wallets.
- No subscriptions, no plans, no invoices, no customer portal, no usage-based
  billing.
- The webhook handler records successful payments, failed payments, and
  refunds. Disputes and chargebacks have no automated handling; a refund that
  exceeds the wallet balance freezes the wallet for operator review.

If Stripe keys are not configured, there is no card path at all and funding is
operator issuance only.

## What is not offered

- **No settlement.** The gateway does not move real money to third parties.
- **No payouts.** Credits cannot be withdrawn or converted back to cash.
- **No compliance reporting.** The ledger is internal metering evidence, not a
  certified financial or compliance record.

The x402 and ACP surfaces authorize and evidence payment demands against
permit budgets. They never mint credits and never write real ledger entries.

## Design-note background

The freeze on additional rails and the fifteen-item checklist any future rail
must satisfy are documented in
[settlement-rails.md](settlement-rails.md), which remains a design note, not a
roadmap commitment. The honest boundary for every money claim is
[SECURITY_LIMITATIONS.md](../SECURITY_LIMITATIONS.md).
