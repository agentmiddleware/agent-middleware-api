# Trust Plane Demo Output

Generated with:

```bash
make demo-trust-plane-check
```

The script sets `API_SURFACE_MODE=full` because it uses direct proof-surface
agent-comms setup and inbox inspection around the governed MCP call. Production
deployments should leave the default `API_SURFACE_MODE=trust_plane` unless they
intentionally need those proof routes.

The exact IDs are intentionally different on every run because the demo uses a
fresh throwaway SQLite database and signs new permits/receipts.

Example proof artifact:

```json
{
  "agent_key_id": "key_c02be307a768",
  "agent_wallet_id": "agt-1e56b078abf4",
  "audit_chain_checked_events": 1,
  "control_loop_verified": [
    {
      "evidence": "/mcp/tools.json includes agent-comms-send",
      "stage": "discover",
      "verified": true
    },
    {
      "evidence": "wallet-bound agent API key created; cross-wallet read returned 403",
      "stage": "authenticate",
      "verified": true
    },
    {
      "evidence": "signed permit permit-f9608a8702ce430b verified for agent-comms-send",
      "stage": "authorize",
      "verified": true
    },
    {
      "evidence": "governed MCP call wrote durable message e2a60305-0ac6-49a2-beea-3ee123b180fc",
      "stage": "invoke",
      "verified": true
    },
    {
      "evidence": "exactly one agent_comms ledger debit was created; replay did not duplicate it",
      "stage": "meter",
      "verified": true
    },
    {
      "evidence": "success receipt rcpt-16b6e8fddbf64053 verified; tampered receipt failed verification",
      "stage": "receipt",
      "verified": true
    },
    {
      "evidence": "wallet audit chain verified; tampered audit event failed verification",
      "stage": "audit",
      "verified": true
    },
    {
      "evidence": "out-of-scope tool data-indexer denied with no ledger debit",
      "stage": "govern",
      "verified": true
    }
  ],
  "cross_wallet_status": 403,
  "denial_reason": "permit_tool_not_allowed",
  "denial_receipt_id": "rcpt-c986c49a75b74d18",
  "denial_replay_receipt_id": "rcpt-c986c49a75b74d18",
  "evidence_bundle_valid": true,
  "inspected_audit_events": 1,
  "inspected_receipts": 1,
  "ledger_entry_id": "a19e065e-bcf7-4e48-a56a-6dc1a377be16",
  "message_id": "e2a60305-0ac6-49a2-beea-3ee123b180fc",
  "paid_pilot_tool": "agent-comms-send",
  "payload_hash": "f3b1cde45b45fa1c99c467cfd9a44641d6d8b8037f790813fade173a5dfddf39",
  "permit_id": "permit-f9608a8702ce430b",
  "receiver_agent_id": "agent-c4071325b605",
  "replay_receipt_id": "rcpt-16b6e8fddbf64053",
  "signing_key_id": "demo-ed25519",
  "sponsor_wallet_id": "spn-50e05ceb01d5",
  "success_receipt_id": "rcpt-16b6e8fddbf64053",
  "tampered_audit_reason": "audit_payload_hash_mismatch",
  "tampered_audit_valid": false,
  "tampered_receipt_reason": "receipt_signature_invalid",
  "tampered_receipt_valid": false
}
```

What this proves:

- The permit is scoped to one MCP tool.
- The scoped tool is `agent-comms-send`, which writes a durable Agent Comms
  inbox row and returns its message ID plus payload hash.
- The successful MCP invocation produces a signed receipt tied to a ledger entry.
- Replaying the same idempotency key returns the same receipt and does not
  create a second debit.
- An out-of-scope MCP tool is denied and produces a denial receipt.
- Replaying that denial returns the same denial receipt and response semantics.
- The agent API key cannot read the sponsor wallet.
- The wallet-scoped audit chain verifies after the governed action, and the
  audit event links back to permit, idempotency key, request hash, and ledger
  entry.
- The buyer-facing evidence bundle validates the receipt, permit, ledger, audit,
  and request-hash links.
- Tampered receipts and tampered audit events fail verification.
- Public signing-key metadata can be inspected without exposing private key
  material.
