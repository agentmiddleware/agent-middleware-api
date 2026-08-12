# AGENTS.md

## Project Mission

This repo is being evaluated as possible trust infrastructure for autonomous agents.
Do not treat it as a generic agent app backend.

The strongest thesis:

> A control layer for agent-to-tool actions where every autonomous action is scoped, authorized, metered, signed, receipted, auditable, and governable.

The weaker thesis to avoid:

> An agent backend with lots of features.

## Core Loop

Judge the product against this loop:

discover → authenticate → authorize → invoke → meter → receipt → audit → govern

Every major feature should support this loop. If a feature does not support this loop, question whether it should be frozen, deleted, or moved out of the main wedge.

## Product Wedge Candidates

When making product or architecture recommendations, evaluate these wedges:

- agent authorization gateway
- signed receipt ledger for agent actions
- usage metering layer for agent tools
- MCP governance proxy
- secure delegated tool execution API
- agent audit log platform

Do not recommend "full agent middleware platform" unless the narrower wedges are already credible.

## Engineering Priorities

Prioritize:

- delegated authority
- permit lifecycle
- scoped authorization
- signed receipts
- usage metering
- replay protection
- idempotency
- tenant isolation
- tool execution safety
- auditability
- revocation
- governance policy
- billing/accounting integrity
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
