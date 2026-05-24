# Production Beta Roadmap

This roadmap defines the minimum product shape for a credible production beta:
an operational control plane for autonomous agents. The product is identity,
billing, discovery, policy, and execution governance for machine-native
software tenants.

## Product Goal

Agent Middleware API should become the default control plane for autonomous
agents that need to discover capabilities, authenticate, invoke tools, meter
usage, and operate inside enforceable boundaries.

The core beta loop is:

```text
discover -> authenticate -> invoke -> meter -> govern
```

1. An agent discovers capabilities through MCP, `.well-known/agent.json`, and `llm.txt`.
2. A developer provisions a sponsor wallet, an agent wallet, and scoped API keys.
3. The agent invokes tools or services using a wallet-scoped key.
4. The platform meters usage, records ledger entries, emits telemetry, and enforces spending limits.
5. Operators inspect failures, cost, keys, security posture, and readiness.

AWI, content generation, oracle crawls, browser control, and sandbox demos are
proof-of-usefulness surfaces. They should strengthen the loop above, not
compete with it in product positioning.

## Beta Acceptance Criteria

### Agent Discoverability

- `GET /mcp/tools.json` returns usable tools for at least one end-to-end demo.
- `GET /.well-known/agent.json` describes auth, billing, and key constraints.
- `GET /llm.txt` gives an agent enough context to authenticate and invoke tools.
- OpenAPI generation passes in CI.

### Wallet And Key Safety

- Env keys in `VALID_API_KEYS` are documented as bootstrap/admin credentials.
- DB-created keys authenticate at runtime.
- DB-created keys are scoped to their issuing wallet only.
- Revoked and expired keys fail authentication.
- Cross-wallet reads and mutations return `403`.
- Ledger, top-up, transfer, dry-run, MCP invoke, API-key management, and sandbox
  access enforce the same ownership model.

### Billing And Monetization

- Sponsor wallet creation works with bootstrap/admin auth.
- Agent wallet provisioning works from a sponsor wallet.
- Service pricing is stable and documented.
- Dry-run billing can estimate multi-step workflows before committing charges.
- Ledger entries can be exported or copied into an invoice workflow.
- Stripe top-up and KYC flows are tested in test mode before any public beta.

### Sandbox And Tool Execution

- Behavioral sandbox endpoints require authentication.
- Sandbox docs clearly state the current isolation guarantees and limits.
- Untrusted code execution is not exposed publicly without a stronger isolation
  layer than a server subprocess.
- MCP invocation accepts normal header auth and enforces wallet access.

### Operator Readiness

- `/health`, `/ready`, and preflight checks are documented.
- Release candidates pass one local release-gate command before tagging:
  `scripts/trust_release_gate.sh`
- Trust-plane changes pass the focused coverage gate:
  `scripts/trust_coverage_gate.sh`
- Bootstrap/admin operators can call `GET /v1/trust/readiness` to see the
  current trust-plane gap map. This report separates verified claims from
  partial, demo-only, or not-yet-claimable gaps; it is not a certification of
  production readiness.
- Production env vars have a complete reference.
- Migrations upgrade an empty database and the latest known production schema.
- CI is green on `master`.
- A release tag includes the exact tested commit.
- Incident response and security reporting paths are documented.

## Governance Spine Sprint Outcome

The Governance Spine Sprint tightened the production-beta release gate around
the core control-plane loop. A release candidate is not ready until the single
gate command above passes the focused trust-plane pytest suite, the canonical
golden path, the executable trust-plane demo proof, discovery drift checks,
committed OpenAPI parity, and the generated simulation inventory check.

## Agent Trust Ledger Outcome

The Agent Trust Ledger makes the governed MCP proof inspectable by operators
without adding a dashboard surface. Admin operators can list permits and
receipts globally; wallet keys can inspect only wallet-scoped permit, receipt,
audit, and ledger records. The one-command demo now proves scoped permit,
strict governed invoke, ledger debit, signed receipt, receipt and audit
inspection, signing-key metadata discovery, replay safety, out-of-scope denial,
and cross-wallet isolation.

Production-like trust mode is now fail-closed: `TRUST_MODE_ENABLED=true`
requires configured signing key material and rejects legacy unpermitted MCP in
production-like environments. Retired public signing-key metadata remains
available so historical permits, receipts, and audit-chain signatures continue
to verify.

The golden path now explicitly tells operators to inspect the policy decision,
audit event, ledger entry, and request or correlation ID for a scoped tool call.
That makes the beta story auditable from discovery through invocation,
metering, and governance.

Wallet-scoped audit inspection is now additive to the operator view: DB-created
wallet keys can list audit events only for their own `wallet_id`, while global
audit queries, summaries, and cross-wallet inspection remain bootstrap/admin
only.

## Policy Bundle Enforcement Outcome

Policy bundles make governance actively enforceable instead of only inspectable.
Bootstrap/admin operators can create wallet-scoped policies at `/v1/policies`
to constrain allowed tools, service categories, per-action cost, real-effects
requirements, risk tier, and human-approval gates. MCP invocation, billing
charges, and planner optimization now evaluate active wallet policies before
execution or charge, and audit metadata records the matched `policy_id` and
evaluated constraints.

## Trust Readiness Gap Map Outcome

The trust-readiness report gives operators a tested, machine-readable map of
what the repo can honestly claim. It marks signed permits, governed MCP replay,
metered ledger debits, signed receipt evidence, audit chains, and wallet-scoped
inspection as verified. The paid-pilot proof now includes `agent-comms-send`, a
real internal MCP tool that writes a durable Agent Comms inbox row in real mode.
It still keeps unresolved gaps visible: AWI remains a draft proof surface,
production settlement and compliance-grade ledger claims are not verified, and
sandbox isolation depends on deployment configuration.

## Recommended Milestones

### Milestone 1: Green And Trustworthy Mainline

- Keep `master` green for tests, ruff, mypy, and OpenAPI generation.
- Add a short CI triage rule: no red mainline should sit without an owner.
- Track type-checking debt separately from runtime security and correctness.

### Milestone 2: One Canonical Golden Path

- Maintain one end-to-end flow in docs and tests:
  bootstrap key -> sponsor wallet -> agent wallet -> agent key -> MCP/tool call
  -> ledger/telemetry inspection.
- Treat this flow as the product heartbeat.

### Milestone 3: Hosted Demo

- Deploy a demo with non-production keys and limited rate limits.
- Publish `mcp/tools.json`, `.well-known/agent.json`, `llm.txt`, and OpenAPI.
- Include sample curl commands and a Python SDK snippet.

### Milestone 4: Production Security Posture

- Complete the threat model in `docs/threat-model.md`.
- Replace subprocess sandbox execution with a stronger isolation boundary before
  offering public arbitrary-code execution.
- Add full action audit semantics: who authorized, what policy allowed, what
  wallet paid, what tool executed, and what telemetry was emitted.
- Add replayable execution records for enterprise and regulated environments.
- Make trust boundaries explicit for container isolation, network policy,
  secrets handling, and execution guarantees.

### Milestone 4b: Policy Engine Depth

- Express wallet, tool, risk, network, and human-approval constraints as explicit policies.
- Ensure planner decisions report the policy and constraint reasons behind selected and rejected actions.
- Treat governance as the near-term strategic center before expanding feature breadth.

### Milestone 5: Commercial Beta

- Verify Stripe test-mode top-up and webhook idempotency.
- Document pricing, refunds, wallet ownership, and operator responsibilities.
- Add a basic admin dashboard or CLI for wallet/key/ledger inspection.

## Non-Goals For Beta

- General-purpose serverless compute.
- Full marketplace settlement for arbitrary third-party providers.
- Complete static typing of every legacy module.
- Public arbitrary-code execution without external sandbox isolation.

## Product Metrics

- Time to first agent tool call: under 10 minutes from clone or deploy.
- Time to provision wallet and scoped key: under 5 minutes.
- Golden-path success rate in CI: 100%.
- Unauthorized cross-wallet access regressions: 0.
- Public demo uptime target: 99% during beta windows.
