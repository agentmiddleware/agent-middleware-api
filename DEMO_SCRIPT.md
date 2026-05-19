# Killer Demo: Governed MCP Tool Call

This demo proves the narrow wedge: an agent tool call that is scoped, metered,
receipted, auditable, replay-safe, and denied when out of scope.

## Environment

```bash
export VALID_API_KEYS=dev-bootstrap-key
export DATABASE_URL=sqlite+aiosqlite:///./trust-demo.db
export TRUST_MODE_ENABLED=true
export ALLOW_LEGACY_UNPERMITTED_MCP=false
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Flow

1. Fetch `/.well-known/agent.json` and `/mcp/tools.json`.
2. Create a sponsor wallet with a bootstrap key.
3. Create an agent wallet.
4. Create an agent API key for the agent wallet.
5. Register or use an MCP tool.
6. Create a permit with:
   - `allowed_tools: ["tool-name"]`
   - `scopes: ["tool:tool-name:invoke", "billing:charge"]`
   - `max_credits`
   - `expires_at`
   - `Idempotency-Key`
7. Invoke `/mcp/messages` with:
   - agent API key
   - `mcpContext.wallet_id`
   - `mcpContext.permit_id`
   - `mcpContext.idempotency_key`
8. Verify `/v1/receipts/verify`.
9. Verify `/v1/audit/verify-chain`.
10. Replay the same MCP request and confirm the receipt ID is unchanged.
11. Invoke a different tool under the same permit and confirm it is denied.

## Proof Artifacts

- Permit JSON with Ed25519 signature.
- Receipt JSON with Ed25519 signature.
- Ledger entry ID referenced by the receipt.
- Audit event ID referenced by the receipt.
- Audit-chain verification response.
