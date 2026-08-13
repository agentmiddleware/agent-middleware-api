# 30-Day Customer Validation Sprint

> **Status: active from 2026-08-12 through 2026-09-11.** This is the
> company-level milestone. It supersedes new core capability work until the
> day-30 decision is recorded.

## Decision To Make

When autonomous agents perform consequential tool calls, do teams have a
painful unmet need to constrain delegated authority and economic exposure,
prevent retry-induced duplicate gateway dispatch or debit, and
independently verify the resulting gateway evidence—and will they deploy and
pay for an inline control boundary?

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

> Give me one tool you are currently afraid to let an autonomous agent invoke.

Then ask:

- What can go wrong, and what is the economic or operational consequence?
- What happens today when the request times out and the agent retries?
- Who authorizes the action and its economic exposure?
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

1. Authorize one economically meaningful but synthetic or redacted action.
2. Execute it under a scoped permit and credit budget.
3. Intentionally repeat the identical request with the same idempotency key.
4. Show the same receipt with no second gateway dispatch or debit.
5. Reuse the key with changed input and observe a fail-closed conflict.
6. Exceed scope or budget and receive verifiable denial evidence.
7. Export and verify the receipt offline in the partner's environment.
8. Record integration time, added latency, operational burden, and failures.
9. Ask, "If this boundary were removed tomorrow, what unacceptable risk
   returns?"
10. Ask, "Will you keep it, who pays, and what is the decision date?"

The gateway's replay guarantee ends at its dispatch boundary. A remote side
effect is exactly once only when the upstream tool also honors the forwarded
idempotency key.

## Buying And Disconfirming Signals

Strong signals:

- A prior incident, near miss, blocked deployment, or quantified exposure.
- A staging endpoint and partner engineer are committed.
- The partner independently values the portable receipt.
- Security or procurement work begins.
- A paid pilot or written commercial commitment exists.

Weak signals:

- "Interesting" or "cool demo."
- Requests unrelated to the one-tool loop.
- No owner, endpoint, engineer, or next date.

Disconfirming signals:

- Existing IAM or gateway controls are considered sufficient.
- Retry duplication has no meaningful consequence.
- Independent evidence is not valued.
- An inline dependency is unacceptable under every supported deployment model.
- No qualified prospect will provide one staging tool after 10 interviews.

## Evidence Log

For every conversation, record:

- Date, company type, and role.
- Consequential tool and action.
- Failure consequence and current workaround.
- Authorization, retry, budget, and evidence gaps.
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
- **Stop core expansion:** prospects will not deploy, do not value portable
  receipts, or consider existing controls sufficient.

Do not create another feature roadmap until one of these decisions is recorded
with its evidence.

## Existing Implementation Documents

- [`WEDGE.md`](../WEDGE.md)
- [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md)
- [`docs/partner-first-tool-runbook.md`](partner-first-tool-runbook.md)
- [`docs/stranger-test.md`](stranger-test.md)
- [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md)
- [`docs/deploy-railway.md`](deploy-railway.md)
