# Trust Plane Demo Output

Generated with:

```bash
make demo-trust-plane-check
```

The exact IDs are intentionally different on every run because the demo uses a
fresh throwaway SQLite database and signs new permits/receipts.

Example proof artifact:

```json
{
  "agent_key_id": "key_cd84a4595f5b",
  "agent_wallet_id": "agt-4b8ae3c2cbe9",
  "audit_chain_checked_events": 1,
  "cross_wallet_status": 403,
  "denial_reason": "permit_tool_not_allowed",
  "denial_replay_receipt_id": "rcpt-5c957b40350e4b3a",
  "denial_receipt_id": "rcpt-5c957b40350e4b3a",
  "inspected_audit_events": 1,
  "inspected_receipts": 1,
  "ledger_entry_id": "543e21a1-5056-4df8-8773-fbf6ba9c720c",
  "message_id": "9db1b81c-547d-4c6f-9339-49836a203130",
  "paid_pilot_tool": "agent-comms-send",
  "payload_hash": "63833f52d411bb26a2c8bb853908232306bce7713b1c3c916f63fd4da7057634",
  "permit_id": "permit-0f62fdfee59640e4",
  "receiver_agent_id": "agent-a4d85a47",
  "replay_receipt_id": "rcpt-26e46941ba4a4bb6",
  "signing_key_id": "demo-ed25519",
  "sponsor_wallet_id": "spn-54322a836193",
  "success_receipt_id": "rcpt-26e46941ba4a4bb6"
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
- Public signing-key metadata can be inspected without exposing private key
  material.
