# Wedge: MCP Governance Proxy

Agent Middleware API should not initially sell itself as a full platform for
autonomous economic actors. The credible wedge is narrower:

> MCP governance and metering for agent tool calls.

The core job is to put one enforceable boundary between autonomous agents and
tools:

```text
discover -> authenticate -> authorize -> invoke -> meter -> receipt -> audit -> govern
```

## Core User

Platform engineering or AI infrastructure teams that already run internal
agents against MCP-style tools.

## First Paid Use Case

Govern and meter internal agent tool calls with wallet budgets, scoped permits,
idempotent retries, signed receipts, and auditable denial.

## What Is Core

- Wallet-scoped API keys.
- MCP discovery and invocation.
- Signed permits for tool scope, wallet binding, budget, expiry, and nonce.
- Idempotency keys for permit issuance and governed invokes.
- Ledger-backed wallet charging.
- Signed receipts for governed tool attempts.
- Tamper-evident wallet audit chains.

## What Is Proof Surface

AWI, browser automation, content generation, oracle crawls, media utilities,
IoT bridges, red-team services, RTaaS, telemetry auto-PR, and sandbox demos are
proof surfaces. They may exercise the control plane, but they do not define the
product until they consume the same permit, receipt, idempotency, and audit
primitives.
