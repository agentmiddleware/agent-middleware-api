# Demo tenant (self-serve Product Hunt keys)

Anonymous visitors can mint their own demo credential and run the
permit → invoke → receipt loop end to end, with no operator involvement:

```bash
# 1. Mint a demo key (no auth; shown once)
curl -s -X POST https://YOUR-HOST/v1/demo/keys | tee demo.json
KEY=$(python3 -c "import json; print(json.load(open('demo.json'))['api_key'])")
WALLET=$(python3 -c "import json; print(json.load(open('demo.json'))['wallet_id'])")
IDEM=$(python3 -c "import uuid; print(uuid.uuid4().hex)")

# 2. Create a permit (issuer = subject = the demo agent wallet)
curl -s -X POST https://YOUR-HOST/v1/permits \
  -H "X-API-Key: $KEY" -H "Idempotency-Key: $IDEM" \
  -H 'Content-Type: application/json' -d "{
    \"issuer_wallet_id\": \"$WALLET\", \"subject_wallet_id\": \"$WALLET\",
    \"allowed_tools\": [\"partner.echo\"],
    \"scopes\": [\"tool:partner.echo:invoke\", \"billing:charge\"],
    \"max_credits\": \"5\",
    \"expires_at\": \"$(python3 -c "from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat())")\"
  }" | tee permit.json
PERMIT=$(python3 -c "import json; print(json.load(open('permit.json'))['permit_id'])")

# 3. Invoke (twice with the same idempotency key: the second replays receipt #1)
for i in 1 2; do curl -s -X POST https://YOUR-HOST/mcp/tools/partner.echo/invoke \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d "{
    \"name\": \"partner.echo\",
    \"arguments\": {\"message\": \"hello from Product Hunt\"},
    \"mcp_context\": {\"wallet_id\": \"$WALLET\", \"permit_id\": \"$PERMIT\",
                      \"idempotency_key\": \"demo-run-1\"}
  }"; done

# 4. Portable receipt + trust keys (keys endpoint is public)
curl -s https://YOUR-HOST/v1/receipts/RECEIPT_ID/portable
curl -s https://YOUR-HOST/.well-known/trust-keys.json
```

## Operator runbook

Everything is OFF by default: merging changes nothing until the flag flips.

- **Turn on:** `ENABLE_DEMO_TENANT=true`. In production-like environments
  `REDIS_URL` must also be set — the server refuses to boot without it, so
  issuance limits are shared across replicas.
- **Turn off instantly:** `ENABLE_DEMO_TENANT=false` (and restart / flip the
  live setting). The issuance route answers 404 AND every existing
  demo-tenant credential is refused at authentication with
  `demo_tenant_disabled`. No sweeper, no waiting for expiry.
- **Revoke everything now:** `POST /v1/demo/admin/revoke-all` (bootstrap
  admin). Returns the revoked count. Single key:
  `POST /v1/demo/admin/keys/{key_id}/revoke` (404 for non-demo keys).
- **Watch:** `GET /v1/demo/admin/stats` (bootstrap admin) returns
  `live_demo_keys`, `issued_last_hour`, `issued_last_day`. Every issuance,
  rate-limit hit, and demo permit/invoke denial logs a structured line on
  logger `app.demo_tenant` (hashed IPs and key ids only — never the raw key
  or raw IP). A Slack/email alert fires at most once per hour when the
  global hourly limit or the live-key cap is hit, or hourly issuance
  crosses `DEMO_ALERT_ISSUES_PER_HOUR`.
- **Visitors manage their own key:** `POST /v1/demo/keys/rotate` (same
  expiry / remaining uses / allowlist / tenant carried over, old key dead
  immediately) and `POST /v1/demo/keys/revoke`, both authenticated with the
  demo key itself.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `ENABLE_DEMO_TENANT` | `false` | Kill switch. Off = issuance 404 + all demo credentials refused. |
| `DEMO_ALLOWED_TOOLS` | `""` (all tools) | Comma-separated tool set. Empty = unrestricted, like a normal wallet-scoped key. When set: minted keys carry it as their allowlist AND demo permits/invokes are capped to it. |
| `DEMO_KEY_TTL_DAYS` | `None` (no expiry) | Key lifetime. Set e.g. `3` for 3-day keys. |
| `DEMO_KEY_MAX_USES` | `None` (unlimited) | Max successful authentications per key. |
| `DEMO_WALLET_CREDITS` | `1000` | Synthetic, out-of-thin-air credit granted to each fresh demo sponsor+agent pair. Funds demo calls; NOT a cap on real money — demo wallets never touch real funds. Max 100000 (dev-keys ceiling). |
| `DEMO_WALLET_DAILY_LIMIT` | `None` (no daily limit) | Daily spend cap on the demo agent wallet, when set. |
| `DEMO_MAX_PERMIT_CREDITS` | `None` (no cap) | Max `max_credits` on a demo-involved permit, when set. |
| `DEMO_MAX_PERMIT_TTL_MINUTES` | `None` (no cap) | Max permit lifetime from now, when set. |
| `DEMO_ISSUE_PER_IP_PER_DAY` | `3` | Keys per client IP per day. |
| `DEMO_ISSUE_GLOBAL_PER_HOUR` | `30` | Keys globally per hour. Alert + 429 past this. |
| `DEMO_ISSUE_GLOBAL_PER_DAY` | `200` | Keys globally per day. |
| `DEMO_MAX_LIVE_KEYS` | `500` | Cap on concurrently live (active, unexpired) demo keys. Alert + 429 past this. |
| `DEMO_ALERT_ISSUES_PER_HOUR` | `20` | Alert when hourly issuance crosses this. |
| `DEMO_ALLOWED_ORIGINS` | `""` | Browser origins allowed to mint. Empty = CLI/SDK/curl (no `Origin`) plus same-host pages only. |

A permit may never outlive the caller key's own expiry, whatever the caps.

## How containment works

Tenant is a property of the **wallet**, not the key:

1. Wallets created under a demo-tenant parent (agent, child, swarm/pod
   members) inherit `tenant="demo"` automatically.
2. Keys created on a demo-tenant wallet are stamped `tenant="demo"`
   automatically, whoever mints them (`/v1/api-keys` create/rotate,
   emergency replacements, auto-rotate).
3. At authentication a credential counts as demo if the key OR its wallet
   is demo-tenant (fail closed), so the kill switch and the route denylist
   cannot be dodged by a key minted before inheritance existed.

On top of that, always on:

- **Permits:** issuer and subject wallets must be in the SAME tenant
  whenever demo is involved — no cross-tenant permits either way, not even
  for bootstrap admins (`demo_permit_out_of_bounds`). Creation already
  requires owning the issuer wallet, so a demo key can only ever mint for
  its own demo family.
- **Money:** the wallet engine refuses any transfer/reclaim whose two
  sides are in different tenants (`cross_tenant_transfer_refused`, 403).
  Charges and refunds are single-wallet by construction; provisioning
  debits are same-tenant by inheritance.
- **Routes:** demo callers are refused with `demo_key_route_forbidden` on
  credential minting (`/v1/api-keys`, `/v1/auth`), fiat/settlement/KYC
  (`/v1/kyc`, `/v1/x402`, `/v1/billing/top-up`,
  `/v1/billing/acp/checkout`, `/v1/webhooks`), wallet creation outside
  issuance (`/v1/billing/wallets/sponsor|agent|child`), cross-wallet groups
  (`/v1/pods`), and trust-plane/admin surfaces (`/v1/signing-keys`,
  `/v1/demo/admin` for non-admins). Everything else a wallet-scoped key
  can reach stays reachable — wallet ownership already confines reads and
  charges to the demo wallet.
- **Keys:** a tenant-labeled (or allowlisted) key counts as bounded, so it
  cannot mint an unrestricted sibling via `/v1/api-keys`; rotation and
  emergency replacements inherit allowlist + tenant, so rotation is never
  an escape hatch.

## Error codes

- `demo_tenant_disabled` (403) — flag off; all demo credentials refused.
- `demo_key_route_forbidden` (403) — demo caller on a denied route.
- `demo_permit_out_of_bounds` (403) — cross-tenant permit, or an optional
  demo cap (tools / credits / TTL) violated.
- `demo_tool_not_allowed` — invoke charges a demo wallet for a tool
  outside the configured `DEMO_ALLOWED_TOOLS` set.
- `key_tool_not_allowed` (403) — caller key's allowlist does not cover
  the permit's tools/scopes or the invoked tool.
- `demo_issuance_rate_limited` (429 + `Retry-After`, `scope` =
  `ip|global_hour|global_day|live_keys`).
- `demo_issuance_unavailable` (503) — counters unreachable in
  production-like (Redis down); fail closed.
- `cross_tenant_transfer_refused` (403) — money movement across tenants.
- `demo_key_required` (403) — demo self-service endpoint called with a
  non-demo credential.

## What a demo key can reach

Read from the code with `ENABLE_PROOF_SURFACES=false` (the production
posture): mounted routers are `CORE_TRUST_ROUTERS` in `app/main.py`, plus
`dev_keys` (triple-gated, local-only), `webhooks` (only with Stripe
configured), and `demo_keys` itself. Dormant (`auth`, `kyc`, `planner`,
`pods`, `x402`, `billing.expansion_router`) and proof-surface routers are
unmounted — and the demo denylist still names the sensitive ones, so
mounting them later cannot open a hole.

A demo key is a wallet-scoped key with full permissions inside the demo
tenant. Reachable route groups (ownership still confines every
wallet-keyed read/charge to the demo wallet):

- **Permits** (`POST /v1/permits`, `GET /v1/permits…`,
  `POST /v1/permits/verify`, `POST /v1/permits/{id}/revoke` for its own):
  core loop. FLAG: `requires_human_approval` permits and
  `POST /v1/permit-requests` page a human through Sentinel (pauseapi.app,
  an outside service) — reachable by design, same as any wallet key.
- **MCP invoke + discovery** (`POST /mcp/tools/{id}/invoke`, `/mcp`,
  `/mcp/messages`, `GET /mcp/tools…`): core loop. FLAG: the configured
  upstream tool dispatches over HTTPS to the partner MCP server (a real
  outside service); in prod that is `partner.echo`
  (`MCP_UPSTREAM_PUBLIC_TOOL_ID`), which only echoes its input.
- **Receipts + evidence** (`GET /v1/receipts…`, `/portable`, `/verify`,
  `GET /v1/evidence/{id}`): reads of its own receipts.
- **Wallet + ledger reads, charge** (`GET /v1/billing/wallets…`,
  `GET /v1/billing/ledger/{id}`, `POST /v1/billing/charge` on its own
  wallet): spends synthetic demo credit only. (Transfers are allowed at
  the route but the engine refuses any cross-tenant pair; top-up/checkout
  fiat routes are denied.)
- **Quotes, policies, permit-requests, audit reads, preflight, discover,
  well-known, docs, health, `/v1/me/…`**: same reads any wallet key gets,
  confined to its own wallet.
- **Demo self-service** (`POST /v1/demo/keys/rotate|revoke`): its own key.

MCP tools a demo key can invoke (registry state at
`ENABLE_PROOF_SURFACES=false`):

- The configured upstream tool when `MCP_UPSTREAM_ENABLED=true` — in prod
  `partner.echo`. FLAG: real HTTPS dispatch to the partner MCP server.
- The local governed dogfood tool `partner.notes.write` only when
  `ENABLE_DOGFOOD_TOOL=true` (default false; refused at boot in
  production-like). Writes notes to local disk — no outside service.
- Proof-surface / second tools only with `ENABLE_PROOF_SURFACES` /
  `ENABLE_DOGFOOD_SECOND_TOOL` (never in prod). Unmounted routers'
  side effects (LLM calls behind `ai`, outbound webhooks, Stripe) are not
  reachable from a demo key in the production posture: the routes are not
  mounted, and the fiat/settlement ones are additionally denied.

Denied even if mounted (short denylist, `demo_key_route_forbidden`):
`/v1/api-keys*`, `/v1/auth*` (JWT mint), `/v1/kyc*`, `/v1/x402*`,
`/v1/billing/top-up*`, `/v1/billing/acp/checkout`, `/v1/webhooks*` (Stripe),
`/v1/billing/wallets/sponsor|agent|child` (creation),
`/v1/pods*`, `/v1/signing-keys*`, `/v1/demo/admin*` (non-admins).
