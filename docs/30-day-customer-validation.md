# 30-Day Customer Validation Sprint

> **Status: active from 2026-08-12 through 2026-09-11.** This is the
> company-level milestone. It supersedes new core capability work until the
> day-30 decision is recorded.

## Decision To Make

When teams keep consequential agent writes read-only or human-gated because
dispatched actions can become ambiguous, will a durable gateway transaction
boundary—logical action identity, bounded authority consumption, at-most-one
dispatch/debit, and explicit `delivery_uncertain`—unlock enough safe autonomy
that they will deploy and pay for it?

This is a customer question, not another technical-proof question. The existing
local and automated proofs show that the repository can enforce its stated
gateway invariants. They do not show that a buyer needs the product.

## Business Invariant

No new core capability without documented evidence from a named prospective
customer.

Work that does not require customer evidence:

- Security or correctness fixes.
- Reliability fixes in the existing one-tool loop.
- Documentation or integration fixes required to complete an active pilot.
- Maintenance needed to keep the existing release gates green.

Unfreezing a capability requires all of the following:

- A named active prospect.
- One concrete consequential tool and action.
- A documented blocker in the prospect's current workflow.
- A committed owner, next action, and date.
- The smallest vertical slice that clears that blocker.

Opinions, speculative roadmap requests, competitor checklists, and demo
enthusiasm do not qualify as customer evidence.

## Target Customer

Platform engineering, AI infrastructure, or security teams already operating
agents against consequential MCP-style tools. Start with teams that can provide
one staging tool and one engineer; do not begin with a broad platform migration.

## Discovery Question

Start with:

> Which consequential action do you prohibit from full autonomy or require a
> human to operate because duplicate or uncertain execution is too risky?

Then ask:

- What can go wrong, and what is the economic or operational consequence?
- What happens today when the request times out and the agent retries?
- After an ambiguous result, what evidence establishes whether retry is safe?
- Who authorizes the action and its economic exposure?
- Can you later prove which exact approval, call allowance, or budget was
  consumed?
- How do you prove what happened afterward?
- Which IAM, gateway, logging, approval, or payment system handles this now?
- Why is the current control insufficient?
- Would you accept another availability, latency, security, and operational
  dependency in the invocation path?
- Who owns the problem, budget, and purchase decision?

Do not ask, "Would you use this?"

## 30-Day Funnel

- Complete 10 problem-discovery interviews.
- Obtain at least 3 named consequential-tool use cases.
- Run 2 technical qualification sessions.
- Secure 1 pilot with a partner-owned agent, tool, and engineer.
- Obtain a paid pilot or written commercial commitment that names the buyer,
  budget path, and decision date.

## Pilot Acceptance Test

All four elements must belong to the design partner:

- Partner-owned agent.
- Partner-owned staging MCP tool.
- Partner engineer operating the workflow.
- Receipt independently verified by that engineer in the partner's environment.

The pilot must:

1. Authorize one consequential, autonomous, retry-sensitive staging mutation
   using synthetic or redacted data.
2. Execute it under a scoped permit and credit budget.
3. Intentionally repeat the identical request with the same idempotency key.
4. Show the same receipt with no second gateway dispatch or debit.
5. Reuse the key with changed input and observe a fail-closed conflict.
6. Exceed scope or budget and receive verifiable denial evidence.
7. Let the partner tool commit and persist one staging effect while its MCP
   response is lost.
8. Observe a signed, charged `delivery_uncertain`; record which configured
   permit credit or call allowance remains consumed.
9. Replay the exact same payload and idempotency key and prove there is no
   second gateway dispatch or debit; have the partner's authoritative lookup
   record whether the partner-side effect count remains one.
10. Have the partner engineer reconcile the actual effect as `applied`,
    `not_applied`, or `unknown` from the partner's authoritative system without
    changing the gateway receipt.
11. Export and verify the receipt offline in the partner's environment.
12. Record integration time, added latency, operational burden, and failures.
13. Ask, "If this boundary were removed tomorrow, what unacceptable risk
   returns?"
14. Ask, "Will you keep it, who pays, and what is the decision date?"

The gateway's replay guarantee ends at its dispatch boundary. The pilot must
not describe `delivery_uncertain` as proof that the partner effect occurred. A
remote side effect is exactly once only when the upstream tool also honors the
forwarded idempotency key; downstream effect truth is reconciled separately.

## Buying And Disconfirming Signals

Strong signals:

- A prior incident, near miss, blocked deployment, or quantified exposure.
- The action is currently read-only or human-gated because retry safety is not
  established.
- A staging endpoint and partner engineer are committed.
- The partner values the combined authority, dispatch, uncertainty, and
  portable-evidence record enough to retain the inline boundary.
- Security or procurement work begins.
- A paid pilot or written commercial commitment exists.

Weak signals:

- "Interesting" or "cool demo."
- Requests unrelated to the one-tool loop.
- No owner, endpoint, engineer, or next date.

Disconfirming signals:

- Existing IAM or gateway controls are considered sufficient.
- Existing gateway controls plus downstream idempotency and effect lookup
  already handle ambiguous execution safely.
- Retry duplication has no meaningful consequence.
- Independently performable verification of linked gateway evidence is not
  valued.
- An inline dependency is unacceptable under every supported deployment model.
- No qualified prospect will provide one staging tool after 10 interviews.

## Evidence Log

For every conversation, record:

- Date, company type, and role.
- Consequential tool and action.
- Current autonomy restriction: read-only, human-gated, or otherwise blocked.
- Failure consequence and current workaround.
- Authorization, retry, budget, and evidence gaps.
- Downstream effect lookup and reconciliation process.
- Inline-dependency objections.
- Existing vendor considered sufficient or insufficient.
- Next committed action, owner, and date.
- Commercial evidence level.
- Requested capability and whether it blocks the one-tool pilot.

Keep confidential names in the private customer system, not this repository;
use a stable prospect identifier here if evidence must be referenced. Never
record secrets, customer payloads, or sensitive production data.

## Day-30 Decision

- **Continue:** one partner-owned pilot passes technically and produces credible
  commercial pull.
- **Narrow or reframe:** repeated pain exists, but buyers demand a different
  primitive or deployment boundary.
- **Stop core expansion:** prospects will not deploy, do not value the combined
  authority/dispatch/uncertainty boundary and its offline-verifiable evidence,
  or consider existing controls sufficient.

Do not create another feature roadmap until one of these decisions is recorded
with its evidence.

## Existing Implementation Documents

- [`WEDGE.md`](../WEDGE.md)
- [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md)
- [`docs/partner-first-tool-runbook.md`](partner-first-tool-runbook.md)
- [`docs/stranger-test.md`](stranger-test.md)
- [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md)
- [`docs/deploy-railway.md`](deploy-railway.md)
