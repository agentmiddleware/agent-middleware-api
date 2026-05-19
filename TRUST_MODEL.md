# Trust Model

The trust model is intentionally narrow: governed MCP tool calls are the first
hard trust boundary.

## Signed Permits

`POST /v1/permits` creates Ed25519-signed authority for a wallet-scoped agent.
A permit binds:

- issuer wallet
- subject wallet
- optional subject API key
- allowed tools
- scopes such as `tool:{tool_name}:invoke` and `billing:charge`
- maximum credits
- expiry
- nonce
- revocation state

Permit creation requires `Idempotency-Key`. Reusing the same key with the same
request returns the original permit. Reusing it with a different request fails
with `409 Conflict`.

## Governed MCP Calls

A governed MCP call supplies `permit_id` and `idempotency_key` in `mcpContext`
or the `Idempotency-Key` header. The server validates wallet binding, key
binding, tool scope, budget, expiry, revocation, and signature before charging.

Legacy wallet-only MCP calls remain available while `TRUST_MODE_ENABLED=false`.
Production trust mode should run with `ALLOW_LEGACY_UNPERMITTED_MCP=false`.

## Signed Receipts

Every successful governed MCP call produces a signed receipt linked to the
permit, ledger entry, audit event, tool, request hash, response hash, and cost.
Denied and failed governed attempts produce signed denial/failure receipts when
a valid permit was present.

## Audit Chain

Control-plane audit events include a payload hash, previous hash, chain hash,
signature, and signing key ID. `/v1/audit/verify-chain` verifies wallet-scoped
audit integrity and detects silent mutation.

## Key Material

The database stores public keys and key metadata only. Production private keys
must come from configured secret material or KMS-backed injection. Local tests
may use process-ephemeral keys; they are not persisted.
