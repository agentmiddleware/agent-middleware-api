# Commercial offer — Agent Middleware API

Status: **offer hypotheses under test.** Not validated tiers, not published prices.
Source: `Agent Middleware API: unit economics reconsidered`, finalized 2026-09-08
(evidence collected 2026-09-05 PT / 2026-09-06 UTC).

Supersedes the "free for 30 days, then $500/month" design-partner offer used in the
2026-09-01 outreach emails. That offer is withdrawn. It was never written down here,
was priced below measured delivery cost at any realistic delivery-hour count, and
should not be restated in any new message.

`public_pricing` stays `false`. `/v1/discover/pricing` stays at zero-cost
`self_hosted` / `design_partner` tiers with no public SLA or pricing claim. Nothing
in this document is implemented in the billing engine — the first pilot is manually
agreed and invoiced. Do not build a pricing engine to execute these numbers.

---

## 1. Setup — the first offer

**$2,500 fixed fee, 20 hours of delivery budget, scope review at 20 hours.**

Deliverable is concrete and bounded:

1. One partner agent.
2. One partner staging MCP tool.
3. Stable operation identity preserved through a retry.
4. One ordinary success.
5. One relevant failure or uncertainty exercise.
6. A receipt verified independently by the partner engineer.
7. Operational handoff plus a recorded delivery time.

Accompany it with a short written acceptance checklist. Scope it to the supported
pilot (synthetic or redacted low-sensitivity workloads, backup and restore drill —
see the deployment SOP).

### Setup sensitivity

Assumes $100 of one-time resource/other expense, $75 per delivery hour, one card
collection, 1% reserve. Excludes sales work (that is acquisition cost) and excludes
the recurring service period unless explicitly bundled.

| Setup fee | 10 delivery hours | 20 delivery hours | 40 delivery hours |
|---|---|---|---|
| $1,000 | $110.70 | -$639.30 | -$2,139.30 |
| **$2,500** | $1,552.20 | **$802.20** | -$697.80 |
| $5,000 | $3,954.70 | $3,204.70 | $1,704.70 |

At 20 hours the $2,500 fee leaves **$802.20** contribution. At 40 hours it **loses
$697.80**. The 20-hour review gate is the control that keeps this from becoming
subsidized consulting.

A $1,000 / 10-hour scope is available only if a buyer will commit to nothing larger.
Treat it as a bounded learning expense, not a healthy engagement.

---

## 2. Recurring — quoted after setup, from the measured service obligation

**Test $1,000–$1,500 per month for a managed workflow.**

$499 is reserved for a demonstrably smaller, lower-touch service obligation. Do not
drop price to compensate for an unconvincing value story — reduce scope or decline
the account.

### What the buyer has to believe

Assumes the buyer values an hour at $100 and an avoided incident at $500 of net
loss. Neither is a measured severity or frequency.

| Monthly fee | Hours saved to break even | Hours for 3x gross benefit | $500 incidents avoided to break even |
|---|---|---|---|
| $499 | 4.99h | 14.97h | 1.00 |
| $999 | 9.99h | 29.97h | 2.00 |
| $1,500 | 15.00h | 45.00h | 3.00 |
| $2,500 | 25.00h | 75.00h | 5.00 |

Monthly net benefit = attributable operating time saved + attributable net losses
avoided − added integration, operating, delay, and review costs − platform fee.

"Attributable" is the whole argument. A failure the buyer's existing idempotency
already prevents is not incremental value. Neither is a new-key duplicate that a
system still accepts as two distinct identities.

---

## 3. Accounting rules

- **Keep setup and recurring separate.** A large first invoice disguises weak
  recurring economics.
- If setup is credited against future subscriptions, model the credit as a reduction
  in later collections, not as cash counted twice.
- **Acquisition is likely the largest per-unit cost.** At $75/acquisition hour plus
  $300 expenses per acquired customer:

| Acquisition effort per win | Cost | Payback | 12-month contribution after acquisition |
|---|---|---|---|
| 10h + $300 | $1,050 | 1.6 months | $6,814.37 |
| 40h + $300 | $3,300 | 5.0 months | $4,564.37 |
| 100h + $300 | $7,800 | 11.9 months | $64.37 |

At 100 hours per win the business is not a business. Record every opportunity's
stage and disqualification reason.

---

## 4. What this offer does not claim

- Not a validated price. No buyer has accepted any of these numbers.
- Not a measured cost per action. The $3.68 previous-period Railway usage is a
  demonstration environment's metered resource charge, not a customer unit cost and
  not a full account bill.
- Not an established Enterprise hosting cost. Resolve which specific pilot
  requirement needs Railway Enterprise, who owns that requirement, and what a
  lower-cost configuration would fail to provide — before promising a managed
  configuration.
- The exactly-once guarantee ends at the gateway dispatch boundary. The upstream
  tool must honor the forwarded idempotency key. Say this in every commercial
  conversation.

---

## 5. Acceptance gates

**Fit:** one named prospect, one consequential staging tool, persistent business
operation identity, an engineer, and a problem the existing contract addresses. If a
simpler configuration of the buyer's current tools solves it, say so and walk.

**Technical acceptance is partner-owned.** The partner demonstrates stable identity
through its own retry path, observes the relevant debit/dispatch outcome, and
verifies a receipt independently. A successful self-issued demo is preparation for
this gate, not the gate.

**Commercial acceptance** is payment, or a written commitment naming buyer, scope,
price, and next date — followed by a recurring decision.

### Continue / stop

Continue on: positive delivery contribution, a credible path to 70% margin at
repeatable scope, manageable acquisition payback, and evidence the buyer prefers
this to its existing integration.

Pause commercialization if qualified prospects consistently lack the identity
discipline the contract requires and will not implement it, value only cheaply
available features, require unbounded support, or reject the price the deployment
requirements need.
