# Design Partner Guide

## Best-Fit Partner

An AI platform team with internal agents that call MCP-style tools and need
budget controls, replay-safe retries, auditability, and proof of authorization.

## Demo Path

1. Create sponsor wallet.
2. Create agent wallet.
3. Issue DB-backed API key for the agent wallet.
4. Issue a signed permit for one MCP tool.
5. Invoke the tool with `permit_id` and `idempotency_key`.
6. Show the ledger debit.
7. Verify the signed receipt.
8. Verify the wallet audit chain.
9. Replay the same request and show no second debit.
10. Attempt an out-of-scope tool and show denial.

## Success Criteria

- The partner can point one internal tool call through the MCP proxy.
- The partner can define a wallet budget and tool scope.
- Retries are safe under the same idempotency key.
- The partner can verify a receipt after the fact.
- The partner can audit who authorized the action, what tool ran, and what it
  cost.

## Do Not Promise Yet

- Settlement rails.
- Compliance-grade ledger storage.
- Full IAM replacement.
- Production sandbox isolation.
- Cross-protocol governance for every agent framework.
