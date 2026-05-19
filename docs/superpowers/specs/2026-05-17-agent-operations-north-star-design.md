# Agent Operations North Star Design

## Purpose

This spec exists to keep Agent Middleware API from drifting into a demo catalog.

The repository already has the raw ingredients of an agent operations control
plane: wallet-scoped auth, billing, MCP discovery, service invocation, planner
constraints, sandboxing, telemetry, health checks, migrations, and a large test
suite. The next phase must make those ingredients act like one coherent
operational spine.

## Guiding Star

Agent Middleware API is agent operations infrastructure.

Its core loop is:

```text
discover -> authenticate -> invoke -> meter -> govern
```

The product must answer these questions for every autonomous agent action:

- Which agent or wallet is acting?
- Which credential authorized it?
- Which capability did it discover?
- Which tool or endpoint did it invoke?
- What did it cost or estimate to cost?
- Which policy allowed or denied it?
- What was recorded for audit, replay, and operator inspection?

If a feature does not strengthen that loop, it is not core product work.

## What Is Bespoke To This Repo

This project is not starting from a blank page. Its advantage is the combination
of surfaces that are already wired together:

- `app/core/auth.py` has `AuthContext`, bootstrap env keys, DB-backed wallet keys,
  revocation, expiration, and exact-wallet checks.
- `app/routers/billing.py` and `app/services/agent_money.py` provide sponsor
  wallets, agent wallets, child wallets, transfers, dry-run billing, Stripe
  top-ups, velocity controls, and exact decimal fields.
- `app/routers/mcp.py`, `app/services/mcp_generator.py`, and
  `app/services/service_registry.py` expose the tool-discovery and invocation
  path that agents will actually use.
- `app/routers/well_known.py`, `app/routers/discover.py`, `/llm.txt`,
  `/openapi.json`, and `docs/golden-path.md` form the discovery contract.
- `app/optimizer/*` and `/v1/planner/optimize` are the first policy-aware
  planner surface.
- `app/audit/lightweight.py`, telemetry routes, health checks, preflight checks,
  and migrations are the seed of governance and operator readiness.

That combination is the thesis. The project must make this spine stronger
before adding more lateral capability demos.

## Product Boundary

Core product work must improve at least one of these primitives:

- identity and authority
- discovery and negotiation
- policy-constrained invocation
- metering and economics
- governance, audit, and replay

Everything else is an adapter, proof surface, or demo.

This boundary is intentionally strict. AWI, Oracle, content generation, browser
control, sandbox execution, IoT, media, red-team, and RTaaS are valuable only
when they prove the control plane. They do not set the roadmap by themselves.

## Redlines

Cut or demote proposal language that says only:

- "agent platform"
- "AI governance"
- "MCP-native"
- "agent marketplace"
- "enterprise-ready"
- "workflow automation"
- "agent intelligence"
- "production-grade"

Those phrases are generic unless tied to a concrete repo behavior:

- a route
- a credential model
- a wallet boundary
- a policy decision
- a ledger record
- an audit event
- a replayable execution record
- a discovery contract test

Keep language that names the mechanism. Remove language that could describe any
agent product.

## Current Sharp Edges

These are the project-specific gaps that most directly weaken the North Star:

### MCP Invocation Split

`/mcp/tools/{service_id}/invoke` uses shared auth context and wallet checks.
`/mcp/messages` currently routes `tools/call` through `mcpContext.wallet_id`
without the same obvious header-auth dependency in the route signature.

For an agent operations control plane, all invocation paths need the same auth,
wallet, policy, billing, and audit semantics. This is a priority.

### Discovery Truth Drift

The repo exposes several discovery surfaces:

- `/.well-known/agent.json`
- `/.well-known/mcp/tools.json`
- `/mcp/tools.json`
- `/llm.txt`
- `/openapi.json`
- `/v1/discover`

These must agree on auth, pricing, capabilities, simulation truth, and route
availability. A stale manifest is not a docs bug; it is an operations bug.

### Policy Is Still Implicit

Wallet access, simulation mode, risk tier, budget, health, and sandbox limits
exist in different places. The planner optimizer has the right shape, but policy
decisions are not yet a shared object that can be audited and reused.

The next control-plane layer must make allow/deny decisions explicit.

### Audit Is Too Thin For The Thesis

The project has lightweight audit hooks, telemetry, and ledger records, but an
operator still needs a clearer answer to:

```text
who acted, with which credential, against which wallet, under which policy,
for what cost, with what result?
```

That answer must become a durable record, not a reconstruction from logs.

## Growth Path

### Phase 1: Make The Golden Path Non-Negotiable

The canonical path must be tested, documented, and easy to run:

```text
bootstrap/admin key
-> sponsor wallet
-> agent wallet
-> scoped agent key
-> discover MCP tool
-> dry-run estimate
-> invoke tool with scoped key
-> committed ledger entry
-> telemetry/audit record
-> operator inspection
```

This is the product heartbeat. Every release must keep it green.

### Phase 2: Unify Invocation Semantics

Every way to invoke a tool must pass through the same pipeline:

```text
auth context -> wallet ownership -> policy decision -> cost estimate
-> execution -> ledger/audit/telemetry record
```

Start with MCP because it is the agent-facing path. Direct HTTP invocation and
sandbox execution converge on the same semantics afterward.

### Phase 3: Make Policy A First-Class Object

Create a small policy decision model with:

- decision ID
- subject wallet/key
- target tool or endpoint
- constraints evaluated
- allow/deny result
- reasons
- simulation mode
- estimated cost
- correlation/request ID

The planner optimizer returns these reasons for selected and rejected actions.
MCP invocation persists the decision before execution.

### Phase 4: Make Discovery Testable

Add contract tests that compare implemented routes and registry data against:

- `/.well-known/agent.json`
- `/mcp/tools.json`
- `/v1/discover`
- `/llm.txt`
- OpenAPI

The test fails when a route, auth requirement, pricing rule, or simulation claim
drifts.

### Phase 5: Make Governance Inspectable

Before building a broad dashboard, expose a narrow operator inspection surface:

- list audit records
- filter by wallet, key, tool, decision, request ID, and time
- export ledger/audit slices
- inspect failed policy decisions
- inspect tool execution records

A CLI or admin API is enough. The important thing is that operators can answer
"what happened and why?" without reading application logs.

### Phase 6: Add Protocol Adapters Only After The Spine Is Strong

Support MCP, A2A, OpenAI Apps SDK, LangGraph, CrewAI, AutoGen, and LlamaIndex as
translation layers over the same core. Do not let any one protocol dictate the
core data model.

Adapter work is valuable when it preserves wallet identity, policy decisions,
metering, and audit. Adapter work is noise when it only adds another demo path.

## Review Tests For Future Work

Ask these before accepting roadmap items or PRs:

- Does this improve the control-plane loop?
- Does it make wallet-scoped authority clearer or safer?
- Does it make autonomous discovery more truthful?
- Does it force all invocation paths through the same controls?
- Does it record cost before and after execution?
- Does it produce an audit trail an operator can trust?
- Does it reduce simulation ambiguity?
- Does it strengthen the golden path?

If the answer is no across the board, keep it out of the core roadmap.

## Non-Goals For The Next Phase

Do not optimize for:

- more standalone demos
- more generated content features
- more browser automation breadth
- general-purpose compute
- a marketplace before invocation and ledger semantics are airtight
- compliance claims before policy, audit, and replay exist
- protocol chasing before the core loop is reliable

## Success Metrics

The North Star is working when:

- The golden path runs locally in under 10 minutes.
- A DB-backed scoped agent key can discover and invoke a tool without
  bootstrap/admin authority.
- Every committed invocation has a wallet, credential source, policy decision,
  cost record, and audit record.
- Discovery surfaces agree on implemented tools, pricing, auth, and simulation
  status.
- Cross-wallet access regressions stay at zero.
- Operators can answer "what happened and why?" from first-party records.
- New feature proposals naturally cite one of the five product primitives.

## Immediate Implementation Priorities

1. Add or tighten the golden-path test around scoped agent key -> MCP/tool call
   -> ledger/audit inspection.
2. Unify `/mcp/messages` and `/mcp/tools/{service_id}/invoke` auth, wallet,
   billing, policy, and audit semantics.
3. Add a route/auth/discovery inventory test for drift across OpenAPI, MCP,
   `.well-known`, `/v1/discover`, and `/llm.txt`.
4. Introduce a policy decision model and return policy reasons from the planner.
5. Persist durable audit records for auth, policy, MCP invocation, billing, and
   sandbox decisions.
6. Add an operator inspection surface before adding a large dashboard.

These priorities are deliberately narrow. They make the current repository more
itself instead of turning it into a different product.
