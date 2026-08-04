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

Marketing host (Vercel):
`https://agent-middleware-web.vercel.app`
(legacy alias still live: `https://site-tawny-seven-33.vercel.app`)

Redeploy Vercel project `agent-middleware-web` after changing these files for them to go live.

## Cross-tool naming convention

Prefix everything with **`agent-middleware-`** so GitHub, Vercel, Railway, and local paths read as one product. Brand wordmarks (e.g. PERMIT) stay provisional and do **not** drive infra names.

| Surface | Name | Notes |
| --- | --- | --- |
| GitHub repo | `PetrefiedThunder/agent-middleware-api` | Canonical product slug |
| Local API / app | repo root (`app/`, …) | Python API |
| Local marketing | `site/` | Keep folder name; maps to Vercel project below |
| Vercel team | `petrefiedthunders-projects` | Account scope |
| Vercel project | `agent-middleware-web` | Static marketing + discovery redirects |
| Vercel production URL | `https://agent-middleware-web.vercel.app` | Prefer this; older `site-*` aliases retained |
| Railway project | `agent-middleware-api` | Matches GitHub |
| Railway service | `api-service` *(legacy)* | Prefer rename to `agent-middleware-api` when safe; do not break `*.up.railway.app` without updating redirects |
| Railway public URL | `https://api-service-production-433c.up.railway.app` | Live API; update `site/vercel.json` redirects if this changes |
| Docker / GHCR | `ghcr.io/petrefiedthunder/agent-middleware-api` | Matches repo |

**Rules**

- Use `agent-middleware-{role}`: `api` (backend), `web` (marketing). Avoid generic names (`site`, `frontend`, `api-service`) for new resources.
- Do not rename the `site/` directory solely for cosmetics — link it to the Vercel project named `agent-middleware-web`.
- Deploy marketing with CLI from `site/` (`vercel --prod --scope petrefiedthunders-projects`).
- **GitHub ↔ Vercel:** project `agent-middleware-web` is linked to
  `PetrefiedThunder/agent-middleware-api` with **Root Directory = `site`**.
  Confirm the first Git-triggered deploy still serves marketing + discovery
  redirects before relying on it over CLI deploys.

  Re-link / verify if needed:

  ```bash
  cd site
  vercel link --yes --scope petrefiedthunders-projects --project agent-middleware-web
  vercel git connect https://github.com/PetrefiedThunder/agent-middleware-api \
    --scope petrefiedthunders-projects
  ```
- Leave Railway service `api-service` until a coordinated rename updates `PUBLIC_URL` + `site/vercel.json` redirects.
- Custom domains later: prefer product DNS (not `site-*.vercel.app` leftovers).

## Brand rename (deferred)

Provisional marketing wordmark **PERMIT** stays until an explicit product
decision. Infra names already use `agent-middleware-*`; do not mass-rename
code, packages, or Railway hosts for cosmetics.
