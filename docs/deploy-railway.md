# Railway deploy SOP (single path)

**Audience:** operators deploying the trust-plane API.  
**Product lens:** [`WEDGE.md`](../WEDGE.md) + [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md).

## Canonical deploy path

**Build and ship from this repo with the in-repo Dockerfile.**

```bash
# From repository root, linked to the Railway service:
railway up
```

Railway uses `railway.json` → `build.builder = DOCKERFILE`. That is the only
supported production image path for this project.

Do **not**:

- Click **Redeploy from GitHub source** in the Railway UI. That can roll the
  service back to an older image / commit than the tree you just verified.
- Treat GHCR `:latest` as the production deploy mechanism. The
  `.github/workflows/docker-publish.yml` workflow publishes optional tags
  (`sha`, branch, semver, `latest` on default branch) for inspection and
  offline use — **not** as the live Railway ship path.
- Commit secrets (`VALID_API_KEYS`, signing keys, Stripe keys) into
  `railway.json` or the git tree.

If you need a reproducible artifact for air-gapped review, pin a GHCR digest
from a release tag (`ghcr.io/<owner>/agent-middleware-api@sha256:…`). Runtime
deploy remains `railway up` from this Dockerfile.

## Required production variables

Mirror of fail-closed rules in `app.core.trust_mode` and
[`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md). Set these on the
Railway service (dashboard or `railway variables set`); do **not** put secrets
in committed defaults.

| Variable | Required value | Notes |
|----------|----------------|-------|
| `ENVIRONMENT` | `production` (or other production-like) | Engages trust guardrails |
| `DEBUG` | `false` | Empty-key auth bootstrap is forbidden in prod-like |
| `ENABLE_PROOF_SURFACES` | `false` | Mount only core trust routers + MCP |
| `ENABLE_DOGFOOD_TOOL` | `true` (optional dogfood) | Opt-in executable `partner.notes.write` for live trust-loop demos. Default in code is `false`. Safe side effect only (append JSONL). Do **not** set `ENABLE_PROOF_SURFACES=true` for this. |
| `TRUST_MODE_ENABLED` | `true` | Shipped default; keep it |
| `ALLOW_LEGACY_UNPERMITTED_MCP` | `false` | Shipped default; keep it |
| `TRUST_SIGNING_PRIVATE_KEY_B64` | strict base64 of exactly 32 raw bytes | Required when trust mode is on in prod-like; PEM, hex, 64-byte concatenations, and double-encoded base64 are invalid |
| `STATE_BACKEND` | `postgres` | Use linked Postgres; avoid silent memory fallback |
| `DATABASE_URL` | from Railway Postgres plugin | App normalizes `postgresql://` ↔ `postgresql+asyncpg://` |
| `PUBLIC_URL` | public HTTPS API origin | e.g. `https://api-service-production-433c.up.railway.app` |
| `VALID_API_KEYS` | operator-set secrets | Bootstrap/admin keys only; **never** `change-me` |
| `RUN_MIGRATIONS_ON_START` | `true` (recommended; set via `railway variables`) | Entrypoint runs `alembic upgrade head` before uvicorn. App boot then **verifies** trust tables exist and **never** calls `create_all` in production-like envs. Flag + empty `DATABASE_URL` fails closed (container exits). If the DB was previously bootstrapped with `create_all` and has no `alembic_version` row, run `alembic stamp head` once before enabling this flag. |

Optional but recommended: `CORS_ORIGINS` locked to known frontends;
`REDIS_URL` only if you intend Redis rate limiting (prod-like fails closed on
Redis outage when set).

Committed `railway.json` may list **non-secret** defaults only
(`STATE_BACKEND`, `PUBLIC_URL`, `ENABLE_PROOF_SURFACES`). It must not contain
`VALID_API_KEYS` or signing material. Set `RUN_MIGRATIONS_ON_START` via
Railway variables (not committed) after confirming Alembic stamp state.

## After deploy — verify

```bash
export API_URL="${PUBLIC_URL:-https://api-service-production-433c.up.railway.app}"

curl -sS "$API_URL/health"
curl -sS "$API_URL/health/dependencies"   # fell_back_to_memory=false; postgres up
curl -sS "$API_URL/.well-known/agent.json"  # proof_surfaces_enabled=false
curl -sS "$API_URL/mcp/tools.json"        # no awi_* / marketplace stubs when proof off
curl -sS "$API_URL/llm.txt"               # Base URL = PUBLIC_URL
```

Expect:

- No `trust_mode_permissive` warning in Railway logs for production.
- `/health/dependencies` → `runtime_degradation.durable_state.fell_back_to_memory=false`.
- `ENABLE_PROOF_SURFACES=false` reflected in health / agent.json.
- If `ENABLE_DOGFOOD_TOOL=true`: `/mcp/tools.json` includes `partner.notes.write`
  and `/health/dependencies` shows `enable_dogfood_tool=true`. Otherwise tools
  list stays empty of dogfood ids.

### Enable live dogfood tool (ops)

After a green deploy of a build that includes the flag:

```bash
railway variables set ENABLE_DOGFOOD_TOOL=true
railway up   # or restart so the process picks up the var
curl -sS "$API_URL/mcp/tools.json" | jq '.tools[].name'
# expect: partner.notes.write
```

Minimal governed invoke (requires an existing agent API key + funded wallet;
do not invent secrets — use your operator key store / `cw-vault`):

```bash
# 1) Discover
curl -sS "$API_URL/mcp/tools.json" | jq .

# 2) Create permit (admin/bootstrap key) — fill WALLET_ID, KEY_ID, ADMIN_KEY
curl -sS -X POST "$API_URL/v1/permits" \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Idempotency-Key: dogfood-live-permit-1" \
  -H "Content-Type: application/json" \
  -d "{
    \"issuer_wallet_id\": \"$WALLET_ID\",
    \"subject_wallet_id\": \"$WALLET_ID\",
    \"subject_key_id\": \"$KEY_ID\",
    \"allowed_tools\": [\"partner.notes.write\"],
    \"scopes\": [\"tool:partner.notes.write:invoke\", \"billing:charge\"],
    \"max_credits\": 20,
    \"expires_at\": \"$(date -u -v+30M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+30 minutes' +%Y-%m-%dT%H:%M:%SZ)\"
  }"

# 3) Invoke (agent key) — fill PERMIT_ID, AGENT_KEY
curl -sS -X POST "$API_URL/mcp/messages" \
  -H "X-API-Key: $AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"id\": \"dogfood-live-1\",
    \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"partner.notes.write\",
      \"arguments\": {\"text\": \"live dogfood note\"},
      \"mcpContext\": {
        \"wallet_id\": \"$WALLET_ID\",
        \"permit_id\": \"$PERMIT_ID\",
        \"idempotency_key\": \"dogfood-live-invoke-1\"
      }
    }
  }"
```

Local full loop without Railway credentials: `make dogfood-trust-plane`.

Operator checklist script (unauthenticated discovery only):

```bash
API_URL="$API_URL" bash scripts/human_preflight.sh
```

## OpenAPI servers note

FastAPI OpenAPI lists `PUBLIC_URL` as the public API server. A
`http://localhost:8000` entry is included only when
`is_production_like_environment(ENVIRONMENT)` is false (local/dev/test/ci).
That is local-dev documentation — not a second deploy target. Production
agents should use `PUBLIC_URL`.

## Related docs

- Human operator checklist: [`human-onboarding.md`](human-onboarding.md)
- Env template: [`.env.example`](../.env.example)
- Tech-debt phases: [`tech-debt-remediation-plan.md`](tech-debt-remediation-plan.md)
