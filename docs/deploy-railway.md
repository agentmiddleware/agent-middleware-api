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
| `TRUST_MODE_ENABLED` | `true` | Shipped default; keep it |
| `ALLOW_LEGACY_UNPERMITTED_MCP` | `false` | Shipped default; keep it |
| `TRUST_SIGNING_PRIVATE_KEY_B64` | secret material | Required when trust mode is on in prod-like |
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
