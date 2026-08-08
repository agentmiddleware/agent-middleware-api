# Settlement Rails: Design Note

**Status:** design note only. No rail beyond Stripe is implemented, planned, or
committed to. Nothing here changes the product boundary in
[`WEDGE.md`](../WEDGE.md).

## The freeze tension, named up front

[`WEDGE.md`](../WEDGE.md) puts **settlement on the freeze list** and forbids
claiming production-ready payments. [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md)
lists "no settlement, dispute, or compliance reporting workflow is implemented"
under *Not Yet Solved (Deferred By Design)*, whose preamble is: keep these out
of the wedge until a design partner requires them.

A strategy input proposed integrating x402 for USDC settlement and Payman for
fiat rails. On its face that is a request to unfreeze a frozen item.

This document does **not** unfreeze it. It is design-only work within the
freeze, and it exists for one reason: if a design partner ever does require a
second rail, the expensive mistake would be discovering the invariants
afterward. Writing them down now costs nothing and commits nothing.

The refusal copy stays exactly as it is. It is duplicated across the README,
`WEDGE.md`, `SECURITY_LIMITATIONS.md`, `DESIGN_PARTNER_GUIDE.md`,
`DEMO_SCRIPT.md`, `static/llm.txt`, the discovery manifest, and the marketing
site. Softening any one surface leaves the repository self-contradictory;
softening the site's line also breaks CI, because a test asserts it verbatim.

## Correcting "partner, don't build"

The recommendation's logic was that partnering avoids building. That is only
half true, and the wrong half is the dangerous one.

**The safety of the money seam is enforced by this repository, not by the
rail.** Stripe's signature proves an event is authentic. It does *not* prove
the event describes an acceptable settlement. The code treats those as two
separate gates, with a distinct exception class for the second — and the second
gate is entirely ours:

- The credit amount is **re-derived from the rail's own settled fields**
  (`amount_received`, with `status == "succeeded"`, currency checked, and
  `amount_received == amount`).
- Client-supplied metadata is then required to **equal the derived value
  exactly**, or the event is rejected. A client-asserted amount is never
  authoritative.
- Duplicate application is prevented by **database UNIQUE constraints** on the
  rail's event and payment identifiers — not by application bookkeeping — and
  only that specific integrity error is swallowed. Every other one is re-raised
  so a real payment is never silently dropped.

Adopting a second rail does not outsource any of that. It means re-implementing
and re-testing all of it against a different rail's semantics. For scale: the
existing single rail carries roughly 900 lines of dedicated negative-path
tests, and `AGENTS.md` designates billing as security-critical, requiring
invalid-input, unauthorized-access, and negative-path coverage.

So the accurate framing is: **partner for the rail, build the verification.**
Any effort estimate that assumes otherwise will be wrong by the cost of the
verification layer, which is the expensive part.

## What is actually true today

The invariants are rail-independent. **The implementation is single-rail.**
Stating it any other way would be the most likely factual error in this
document.

Concretely, there is no `SettlementRail` protocol, no adapter registry, no
`settlement_events` table, and no rail discriminator column. The seam is one
concrete `StripeIntegration` class plus two Stripe-named UNIQUE columns on
`ledger_entries` (`payment_intent_id` and `stripe_event_id`) — alongside a
third, `stripe_session_id`, which is merely indexed and is never written by any
code path, since every writer of that name targets the KYC table instead. A
rail-agnostic boundary is something to be **extracted**, not something that
exists.

Inert hints of the original intent survive: the deprecated top-up request
schema and both service-layer `top_up` signatures still carry a
`payment_method` parameter defaulting to `"stripe"` — on a path that now
returns `410 Gone`.

### How credits come into existence

Exactly two code paths increase total credit supply:

1. `StripeIntegration._mint_credits` — the only path driven by an external
   event. It locks the wallet row `FOR UPDATE`, requires a sponsor wallet, and
   writes one credit ledger entry carrying the rail's payment identifier.
2. `WalletEngine.create_sponsor_wallet` with `initial_credits > 0` — gated on
   bootstrap-admin credentials, with an in-code rationale that this endpoint
   *is* the operator's fiat-to-credit conversion.

Note the precision required here: it is wrong to say credits can only be
created by verified settlement. They can also be created by **explicitly
admin-gated operator issuance**. Everything else in the system moves credits
rather than creating them — agent wallet provisioning debits the sponsor and
writes paired transfer entries, and internal refunds reverse one specific prior
debit and cannot create supply.

Direct top-up is dead at both layers: the route is declared deprecated with a
`410 Gone` contract, and the service method raises unconditionally. A client
token is never treated as proof of payment.

## The rail conformance checklist

This is the durable deliverable. Any rail — x402, Payman, ACH, a card
processor, or something that does not exist yet — must satisfy every item
before it touches the ledger. It is derived from what the Stripe path actually
enforces, generalized.

**Authenticity**
1. Settlement notifications are cryptographically verifiable against a secret
   or key the operator holds, and verification failure is a hard rejection.
2. Verification is shared code, not re-implemented per consumer. (The
   repository currently fails this: the KYC webhook handler and the settlement
   handler verify the same signing secret with different exception handling and
   no shared helper.)

**Settlement validity — separate from authenticity**
3. The credited amount is re-derivable from fields the *rail* controls, never
   from client-supplied metadata.
4. Any client-supplied amount must be checked for exact equality against the
   derived value and rejected on mismatch.
5. The currency and settled-status fields are validated explicitly against an
   allowlist, not assumed.

**Identity and idempotency**
6. The rail supplies a stable, unique event identifier suitable for a database
   UNIQUE constraint.
7. Duplicate and out-of-order redeliveries are provably non-minting and
   non-double-debiting, under test.
8. Only the specific duplicate-identity integrity error is swallowed; all
   others propagate.

**Finality and reversal** — the gap the current design does not name
9. The rail's finality model is documented: when is a settlement irreversible?
   Stripe's is "succeeded now, possibly refunded later." An on-chain stablecoin
   rail is typically irreversible after some confirmation depth with no
   chargeback. An ACH-style fiat rail has return windows measured in days.
   **These three are not interchangeable and the current code models only the
   first.**
10. The reversal policy is explicit about who bears the loss. Today's answer is
    implicit and Stripe-specific: preserve the negative balance as the sponsor's
    durable liability, freeze the wallet, and raise a critical alert for
    operator review. Whether that generalizes is undocumented.
11. Partial and cumulative reversals apply only the new delta. (The current
    implementation does this correctly but detects prior partial refunds by
    **exact string matching on a ledger description field** — a latent
    fragility that any second rail should not copy.)

**Denomination**
12. The fiat-to-credit rate is currently a single global constant
    (1000 credits = $1.00 USD), per-deployment and not per-rail. A rail
    denominated in anything else — including a nominally 1:1 stablecoin —
    forces a decision the codebase has not made: whether the rate is snapshotted
    onto the settlement event, and where FX risk lands. There is no per-rail
    rate, no rate stored on the ledger entry, and no oracle concept.

**Interaction model**
13. Stripe is **push-only**: webhook arrives, credits mint. Nothing in the
    codebase models the two other shapes a rail may require — verifying a
    payment proof presented *inline with a request*, or *polling* a rail for
    confirmation. Adopting a pull/verify rail is not an adapter swap; it is a
    new interaction model.

**Operational**
14. There is an identity/compliance gate for the rail. Today that is Stripe
    Identity gating top-up preparation; a non-Stripe rail has no provider
    behind that gate.
15. Aggregate minted credits reconcile against the rail's own reported balance.
    **Nothing does this today** — no job, report, or invariant check asserts
    that live credits are backed by verified settlements. With one rail this is
    a latent gap; with several it becomes materially dangerous.

## On x402 and Payman specifically

**This repository contains no basis for any claim about either.** Outside this
note and its companion [`PRODUCT_STRATEGY.md`](PRODUCT_STRATEGY.md), the strings
`x402`, `USDC`, `Payman`, and `stablecoin` appear zero times across the entire
repository. There is no prior art, no design note, no dependency, and no TODO.

Two related things in the repo must not be misread as evidence of crypto
direction:

- In the codebase, `crypto` appears only in the *cryptography* sense —
  audit-chain hashing, a JWT extra, HSM/KMS hardening. The only
  cryptocurrency-sense uses are in [`../GOVERNANCE.md`](../GOVERNANCE.md), which
  declines a crypto-thesis investor precisely because the project has no such
  thesis.
- `blockchain` / `on-chain` appear only as an **optional, unimplemented**
  proposal to anchor the audit chain's Merkle root, explicitly marked skippable.
  That is about tamper-evidence for the audit log, not about moving money.

Accordingly, this document asserts nothing about what x402 or Payman provide —
their finality guarantees, callback signature schemes, idempotency primitives,
identifier stability, or reversal semantics are all unverified here. Evaluating
either means answering the fifteen checklist items above with citations to their
documentation, and that evaluation has not been done.

The checklist is deliberately the deliverable rather than a rail comparison. A
snapshot of two products' capabilities goes stale; the invariants do not.

## If a partner ever forces this

Sequenced so that nothing is built before it is needed:

1. **A real design partner names a rail and a reason.** Absent that, stop here —
   this is the freeze working as intended.
2. **Answer the fifteen checklist items** for that rail, in writing, with
   citations. Items 9 through 13 are where a rail is most likely to be
   disqualified.
3. **Extract the boundary from the existing implementation**, following the
   precedent already set by the upstream MCP adapter, which owns only remote
   transport concerns and leaves permits, metering, persistence, receipts, and
   audit to the governed layer. A settlement adapter should mirror that shape
   exactly: own rail transport and rail-specific validation; leave minting,
   ledger writes, and locking in the shared layer.
4. **Generalize the schema**: replace the three Stripe-named columns with a
   `(rail, external_event_id)` pair under a composite UNIQUE constraint, plus a
   rail discriminator, with a migration that backfills existing rows as
   `stripe`. Do this *before* the second rail exists, not during.
5. **Reproduce the negative-path test suite** for the new rail. This is the
   bulk of the work.
6. **Build the treasury reconciliation job** (item 15) before operating two
   rails, not after.

Only then does any public claim change — and it would change to something
narrow, like "credits may be funded through a verified *rail*", never to
"production settlement."

## Fixes worth doing regardless

These are small, in-scope today, and reduce risk whether or not a second rail
ever appears:

- Share one webhook signature-verification helper between the settlement and
  KYC handlers so both catch signature-verification failures identically.
- Make `_handle_payment_failed` use the safe field accessor the other handlers
  use, rather than raw dictionary access.
- Replace string-matched prior-refund detection with a structured reference.
- Add request-level idempotency to top-up preparation. Repeated prepares mint
  nothing extra — the webhook path is safe — but they do create redundant
  payment intents.
- Add the treasury reconciliation check (item 15) for the single rail that
  exists.
