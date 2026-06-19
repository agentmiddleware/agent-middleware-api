# Design Partner Guide

Use this guide to qualify design partners for the concrete trust-plane proof:
scoped signed permit, governed MCP invoke, wallet charge, signed receipt,
ledger entry, audit chain, replay safety, and out-of-scope denial.

## Best-Fit Partner

An AI platform, infrastructure, or security engineering team that already has
internal agents calling MCP-style tools and needs a practical control point for:

- Tool-level authorization.
- Wallet or budget-backed metering.
- Replay-safe retries.
- Post-hoc receipt verification.
- Audit evidence for who authorized what, what ran, and what it cost.

This is best for teams that can bring one real internal tool call to the demo.
It is not yet a fit for teams seeking production settlement, a full IAM
replacement, or universal governance across every agent framework.

## Demo Path

Run the focused one-command proof first:

```bash
make demo-trust-plane
```

If the partner wants the operator narrative instead of the compact proof, run:

```bash
make agent-ops-war-room
```

If the partner is from a security team and wants to see the boundary hold
under attack rather than just on the happy path, run the adversarial battery:

```bash
make red-team-trust-plane
```

It drives one valid permit and attacks it ten ways — no permit, unknown
permit, out-of-scope tool, missing scope, over-budget, stolen permit (wrong
wallet), wrong key, expired, revoked, and tampered signature — and asserts
each is denied with a concrete reason code, that none produces a ledger debit,
and that a final valid call still charges exactly once.

Then walk the partner through the live flow:

1. Create a sponsor wallet.
2. Create an agent wallet.
3. Issue a DB-backed API key for the agent wallet.
4. Issue a signed permit for one MCP tool with wallet binding, allowed tool,
   `billing:charge`, budget, expiry, nonce, and idempotency.
5. Invoke the tool through governed MCP with `permit_id` and
   `idempotency_key`.
6. Show the wallet charge in the ledger.
7. Verify the signed receipt.
8. Verify the wallet audit chain.
9. Replay the same request and show the same receipt ID with no second debit.
10. Attempt a different tool under the same permit and show out-of-scope
    denial.
11. Attempt the same allowed tool with no permit at all and show the
    `permit_required` denial, proving the trust plane fails closed when
    `ALLOW_LEGACY_UNPERMITTED_MCP=false`.

## What To Listen For

- "Can this sit in front of one of our internal MCP tools?"
- "Can we tune permit scopes, budgets, and expiry per agent or workflow?"
- "Can our operators verify receipts without trusting application logs?"
- "Can retries be safe when an agent or orchestrator repeats a request?"
- "Can denial evidence be audited, not just returned to the caller?"

## Success Criteria

- The partner can point one internal tool call through the MCP proxy.
- The partner can define a wallet budget and tool scope.
- Retries are safe under the same idempotency key.
- The partner can verify a receipt after the fact.
- The partner can audit who authorized the action, what tool ran, and what it
  cost.
- The partner can see an out-of-scope request denied with an explicit reason.

## Positioning Language

Use:

- "Governed MCP trust plane for scoped, metered tool calls."
- "Signed proof of authorization and execution for a single tool boundary."
- "Replay-safe billing and audit artifacts for partner evaluation."

Avoid:

- "Production-ready agent payments."
- "Autonomous economic actor infrastructure."
- "Complete policy layer for all agent frameworks."
- "Compliance-grade ledger or audit storage."

## Do Not Promise Yet

- Settlement rails.
- Compliance-grade ledger storage.
- Full IAM replacement.
- Production sandbox isolation.
- Cross-protocol governance for every agent framework.
- Key-management hardening beyond the current trust-plane proof.
