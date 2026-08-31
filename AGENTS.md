# AGENTS.md

## Project Mission

This repo is being evaluated as possible trust infrastructure for autonomous agents.
Do not treat it as a generic agent app backend.

The strongest thesis:

> Transaction integrity for consequential autonomous tool actions. For one
> logical action, the supported gateway path binds delegated authority and
> configured consumption, permits at most one gateway dispatch and debit,
> preserves uncertain delivery as durable state, and links the resulting
> gateway evidence.

The weaker thesis to avoid:

> A broad agent backend, governance platform, or bundle of IAM, policy,
> budget, logging, and receipt features.

## Core Loop

Judge the product against this loop:

logical action identity → authorize → reserve configured allowance → debit →
claim one gateway dispatch → classify outcome or uncertainty → receipt/audit →
reconcile

"Transaction" means a durable linked state machine at the gateway boundary,
not one distributed ACID transaction with the upstream tool. Every major
feature should support this loop. If a feature does not support it, question
whether it should be frozen, deleted, or moved out of the main wedge.

## Current Company Phase: Customer Validation

The active company milestone is the 30-day customer-validation sprint in
`docs/30-day-customer-validation.md`, not another core release.

Apply this business invariant:

> No new core capability without documented evidence from a named prospective
> customer.

Work may proceed without new customer evidence only when it is:

- a security or correctness fix
- a reliability fix in the existing one-tool loop
- a documentation or integration fix required to complete an active pilot
- maintenance required to keep existing release gates green

Before unfreezing a capability, require one named active prospect, one concrete
consequential tool, a documented current-workflow blocker, a committed owner and
date, and the smallest vertical slice that clears the blocker. Demo enthusiasm,
generic competitor parity, and speculative roadmap requests are not evidence.

Judge external validation against the partner-owned milestone: one partner
agent, one consequential retry-sensitive staging mutation, and one partner
engineer. The partner must run a controlled effect-then-response-loss case,
observe charged `delivery_uncertain` and no second gateway dispatch/debit on
exact replay, reconcile the actual effect from its authoritative system, and
verify the linked gateway receipt offline. Do not count local demos,
self-issued public proof, or the stranger test as customer validation.

## Product Wedge

The active wedge is transaction integrity for consequential autonomous
actions: mutations whose duplicate, incorrect, or uncertain execution can
cause material harm and whose retry safety matters.

IAM, generic tool authorization, payment rails, budget controls, receipts,
logging, and governance are integrations or supporting mechanisms—not
standalone differentiation. Do not recommend a "full agent middleware
platform" unless this narrower wedge is first credible with customers.

## Engineering Priorities

Prioritize:

- logical-action identity and payload binding
- bounded permit, approval, credit, and call-allowance consumption
- one-shot gateway dispatch
- explicit `delivery_uncertain`
- safe non-redispatch and reconciliation
- upstream idempotency propagation
- linked execution-time evidence
- delegated authority and permit lifecycle
- scoped authorization and revocation
- replay protection and idempotency
- billing/accounting integrity
- tenant isolation
- tool execution safety
- signed receipts and auditability
- developer SDK/demo path

## Security-Critical Areas

Treat these as security-critical:

- auth
- authorization
- tenants
- permits
- delegations
- receipts
- billing/metering
- audit logs
- tool execution
- secrets
- CI/CD
- deployment
- migrations

For changes in these areas, include tests for invalid input, unauthorized access, and relevant negative paths.

## Agent-Specific Risks

Always consider:

- prompt injection
- tool injection
- agentic workflow injection
- confused deputy attacks
- replay attacks
- permit misuse
- over-budget invocation
- billing double-charge
- unsafe tool execution
- unverifiable receipts
- weak key management
- cross-tenant data leakage

## Analysis Rules

When analyzing the repo:

- cite specific files and functions
- separate README claims from code evidence
- separate real flows from stubs or demos
- identify overbuilt or unfocused areas
- recommend what to freeze/delete, not only what to build

Use reality levels:

- verified
- partially verified
- not verified
- stubbed
- demo-only
- misleading
- contradicted
- too early to tell

## Implementation Rules

Prefer vertical slices over broad skeletons.

A good change usually includes:

- one focused behavior
- one clear model/service/route change
- tests proving the behavior
- negative-path tests where relevant
- minimal public API disruption

Do not introduce new dependencies unless necessary and justified.

## Local Credentials for Agents

When you need an API key against a local instance, provision your own —
do not ask for production secrets and never hardcode keys:

- **Admin-shaped local testing**: run
  `python scripts/generate_static_dev_keys.py`, put the printed value in
  `.env` as `STATIC_DEV_API_KEYS=...`, and restart the server. Static
  `amw_dev_` keys are bootstrap admins in local-compatible environments
  only and are deliberately never rotated.
- **Wallet-scoped keys with no restart** (server already running with
  `ENABLE_DEV_KEY_SELF_PROVISION=true`): `POST /v1/dev-keys/self-provision`
  mints a sponsor wallet, agent wallet, and wallet-scoped key with no
  pre-shared secret. Use this to exercise the real permit → invoke →
  receipt loop as a non-admin caller.

Both surfaces are refused by production-like deployments at boot. Details:
`docs/static-dev-api-keys.md`.

## Final Summary Format

End every task with:

- Files changed
- What changed
- Tests run
- What passed
- What was not tested
- Remaining risks
- Recommended next step
