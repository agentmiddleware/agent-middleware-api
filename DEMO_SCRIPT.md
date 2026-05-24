# Demo Script: Concrete Trust-Plane Proof

This is the design-partner demo for the current trust-plane proof. It shows one
bounded agent tool call moving through the control plane:

```text
scoped signed permit -> governed MCP invoke -> wallet charge -> signed receipt
-> ledger -> audit chain -> replay no double charge -> out-of-scope denial
```

The proof is intentionally narrow. It demonstrates that the governed MCP path
can enforce scope, meter a call, produce verifiable artifacts, and reject misuse.
It does not claim production readiness, settlement rails, or a complete
autonomous economic actor infrastructure.
The happy-path tool is `agent-comms-send`, an internal MCP tool that writes a
SQL-backed Agent Comms inbox message when `SIMULATION_MODE_AGENT_COMMS=false`.

## Environment

Run the API in trust mode:

```bash
export VALID_API_KEYS=dev-bootstrap-key
export DATABASE_URL=sqlite+aiosqlite:///./trust-demo.db
export TRUST_MODE_ENABLED=true
export ALLOW_LEGACY_UNPERMITTED_MCP=false
export SIMULATION_MODE_AGENT_COMMS=false
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## One-Command Proof

For a local proof that exercises the real FastAPI routers, a throwaway SQLite
database, signed trust artifacts, and the governed MCP path without running a
server:

```bash
make demo-trust-plane
```

For CI or pre-merge verification:

```bash
make demo-trust-plane-check
```

For an operator-facing timeline that is easier to narrate in a live design
partner walkthrough:

```bash
make agent-ops-war-room
```

For machine-readable verification of the same war-room flow:

```bash
make agent-ops-war-room-check
```

The proof artifact shape is captured in
[`docs/demo-trust-plane-output.md`](docs/demo-trust-plane-output.md). Use the
live demo flow below when walking a partner through the product story.

## Live Demo Flow

1. Fetch `/.well-known/agent.json` and `/mcp/tools.json`.
2. Create a sponsor wallet with a bootstrap key.
3. Create an agent wallet.
4. Create an agent API key for the agent wallet.
5. Register an Agent Comms receiver and discover `agent-comms-send`.
6. Create a signed permit with:
   - `allowed_tools: ["agent-comms-send"]`
   - `scopes: ["tool:agent-comms-send:invoke", "billing:charge"]`
   - `max_credits`
   - `expires_at`
   - `Idempotency-Key`
7. Invoke `/mcp/messages` with:
   - agent API key
   - `mcpContext.wallet_id`
   - `mcpContext.permit_id`
   - `mcpContext.idempotency_key`
8. Show the wallet charge in the billing ledger and the durable inbox message.
9. Verify the signed receipt with `/v1/receipts/verify`.
10. Inspect the signed receipt with `/v1/receipts` and
    `/v1/permits/{permit_id}/receipts`.
11. Inspect the permit with `/v1/permits/{permit_id}` and the active public
    signing key with `/v1/signing-keys/active`.
12. Verify the wallet audit chain with `/v1/audit/verify-chain`.
13. Replay the same MCP request and confirm the receipt ID is unchanged and no
    second ledger debit appears.
14. Invoke a different tool under the same permit and confirm the request is
    denied as out of scope.

## Talk Track

- "The permit is the bounded authority: wallet, tool, scope, budget, expiry,
  nonce, and signature."
- "The MCP invocation is not just authenticated. It is checked against the
  permit before the tool is allowed to run."
- "A successful governed invoke charges the wallet once, emits a signed receipt,
  and ties that receipt back to the ledger entry and audit event."
- "Replaying the same request returns the same receipt instead of charging
  again."
- "Trying a different tool with the same permit is denied, which is the core
  governance behavior partners need to see."

## Proof Artifacts

- Permit JSON with Ed25519 signature.
- Receipt JSON with Ed25519 signature.
- Public signing-key metadata, with no private key material.
- Ledger entry ID referenced by the receipt.
- Agent Comms message ID and payload hash produced by `agent-comms-send`.
- Audit event ID referenced by the receipt.
- Permit and receipt inspection responses filtered to the agent wallet.
- Audit-chain verification response.
- Replay response with the same receipt ID and no duplicate debit.
- Out-of-scope denial response such as `permit_tool_not_allowed`.

## Keep The Claim Narrow

Say: "This proves a governed MCP trust-plane path for scoped, metered,
replay-safe tool calls."

Do not say: "This is production-grade agent banking," "full autonomous economic
actor infrastructure," or "complete cross-framework governance."
