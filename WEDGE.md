# Wedge: Exactly-once MCP permits

Agent Middleware API should not initially sell itself as a full platform for
autonomous economic actors. The credible wedge is narrower:

> Exactly-once permits and receipts for metered MCP calls.

Or in one line:

> Authorize one agent action. Charge it once. Prove what happened.

The core job is to put one enforceable **economic** boundary between autonomous
agents and tools:

```text
scoped signed permit -> governed MCP invoke -> wallet charge -> signed receipt
-> ledger -> audit chain -> replay no double charge -> out-of-scope denial
```

Category language (“MCP trust plane,” “governance gateway”) is occupied. The
differentiating primitive is exactly-once economic authorization: one
idempotency key returns the original receipt without a second tool execution or
debit.

## Positioning vs nearby products

Stay a **closed-loop credit and delegated-authority** system for internal AI
platform teams—not a general MCP gateway and not merchant settlement.

| Nearby | Their center of gravity | Our difference |
|--------|-------------------------|----------------|
| MCP “trust” gateways (e.g. signed receipts + replay) | Policy / evidence | Wallet debit + economic idempotency |
| MCP monetization / pay-per-tool | Payments rails | Internal budgets; no settlement claim |
| Enterprise authz for MCP | Who may call | Meter + receipt + charge-once |

Do not pitch as production payments, compliance-grade ledger, or IAM
replacement (see [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md)).

## Core User

Platform engineering or AI infrastructure teams that already run internal
agents against MCP-style tools and need a control point before those tools are
invoked.

## First Paid Use Case

Govern and meter internal agent tool calls with wallet budgets, scoped permits,
idempotent retries, signed receipts, and auditable denial.

The first design-partner motion should be one real internal tool behind the
proxy, not a broad migration of every agent workflow.

## Design Partner First Tool

Reference proof tool (local demo only): `trust-plane-echo` via
`make prove-trust-plane` / [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

Partner swap checklist:
[`docs/partner-first-tool-runbook.md`](docs/partner-first-tool-runbook.md).

Partner motion:

1. Keep `ENABLE_PROOF_SURFACES=false` in the partner environment.
2. Register **one** internal MCP tool (replace echo; do not mount AWI/media/etc.).
3. Issue a wallet-scoped permit for that tool only.
4. Walk permit → invoke → charge → receipt → replay → out-of-scope deny.
5. Stop. Do not expand surface until that loop is trusted in their stack.

## What Is Core

- Wallet-scoped API keys.
- MCP discovery and invocation.
- Signed permits for tool scope, wallet binding, key binding, budget, expiry,
  and nonce.
- Idempotency keys for permit issuance and governed invokes.
- Ledger-backed wallet charging.
- Signed receipts for governed tool attempts.
- Tamper-evident wallet audit chains.
- Explicit denial reasons for out-of-scope or invalid governed attempts.

## What The Current Proof Shows

- A permit can bind one agent wallet to one allowed MCP tool and budget.
- A governed MCP invoke can validate that permit before the tool call proceeds.
- A successful governed invoke can charge the wallet and write a ledger entry.
- The response can include a signed receipt linked to permit, ledger, and audit
  identifiers.
- The audit chain can be verified after the fact.
- Replaying the same governed invoke can return the same receipt without a
  duplicate debit.
- A request outside the permit scope can be denied with a concrete reason.

## What Is Proof Surface

AWI, browser automation, content generation, oracle crawls, media utilities,
IoT bridges, red-team services, RTaaS, telemetry auto-PR, and sandbox demos are
proof surfaces. They may exercise the control plane, but they do not define the
product until they consume the same permit, receipt, idempotency, and audit
primitives.

## What To Freeze

- New proof-surface features and ungated HTTP demos.
- Broad multi-tool migrations before one partner tool is live.
- KMS, settlement, transparency logs, and non-MCP adapters (see
  [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md)).

Production-like deploys must keep `ENABLE_PROOF_SURFACES=false`.

## What Not To Claim Yet

- Production-ready payments or settlement.
- Compliance-grade ledger storage.
- Full autonomous economic actor infrastructure.
- Universal policy enforcement across every agent framework.
- A replacement for enterprise IAM, secrets management, or sandbox isolation.
