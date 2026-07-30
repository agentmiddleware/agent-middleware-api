# Marketing site draft

Provisional static landing for exactly-once MCP permits (closed-loop credits).
Brand wordmark is a placeholder — not affiliated with Permit.io.

## View locally

```bash
cd site && python3 -m http.server 8765
```

Open http://127.0.0.1:8765/

## Scope

- Hero: authorize / charge once / prove — see the proof (not live crypto)
- Proof: success → replay (same receipt) → deny; notes `permit_required`
- Partner path: `make dogfood-trust-plane` + runbook link
- Explicit non-claims

Illustrative receipt IDs use live shapes (`rcpt-`, `permit-`, UUID ledger).
Dogfood numbers: `credits_per_unit=2.0`, idempotency `dogfood-invoke-1`.
Signature on the page is a base64 placeholder; run dogfood +
`/v1/receipts/verify` for a real signature.

No live metering, signup, or API keys on this page.
