# Wedge: MCP Trust Plane

Agent Middleware API should not initially sell itself as a full platform for
autonomous economic actors. The credible wedge is narrower:

> A governed trust plane for scoped, metered MCP tool calls.

The core job is to put one enforceable boundary between autonomous agents and
tools:

```text
scoped signed permit -> governed MCP invoke -> wallet charge -> signed receipt
-> ledger -> audit chain -> replay no double charge -> out-of-scope denial
```

## Core User

Platform engineering or AI infrastructure teams that already run internal
agents against MCP-style tools and need a control point before those tools are
invoked.

## First Paid Use Case

Govern and meter internal agent tool calls with wallet budgets, scoped permits,
idempotent retries, signed receipts, and auditable denial.

The first design-partner motion should be one real internal tool behind the
proxy, not a broad migration of every agent workflow.

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

## What Not To Claim Yet

- Production-ready payments or settlement.
- Compliance-grade ledger storage.
- Full autonomous economic actor infrastructure.
- Universal policy enforcement across every agent framework.
- A replacement for enterprise IAM, secrets management, or sandbox isolation.
