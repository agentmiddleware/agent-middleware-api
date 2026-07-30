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

## Agent discovery (not human SEO)

This host should help machines find the API:

- `/.well-known/agent.json` — pointer with absolute API discovery URLs
- `/llm.txt` and `/llms.txt` — short bootstrap prose pointing at the API
- Footer / nav links to the live Railway discovery surfaces
- Vercel redirects for `/mcp/tools.json`, `/v1/discover`, `/openapi.json` → API

Canonical machine base URL:
`https://api-service-production-433c.up.railway.app`

Redeploy the Vercel project after changing these files for them to go live.
