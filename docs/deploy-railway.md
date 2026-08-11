# Railway deploy SOP (single path)

**Audience:** operators deploying the trust-plane API.  
**Product lens:** [`WEDGE.md`](../WEDGE.md) + [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md).

## Canonical deploy path

**Build and ship from this repo with the in-repo Dockerfile.**

```bash
# From repository root, linked to the Railway service:
DEPLOY_SHA="$(git rev-parse HEAD)"
railway variable set BUILD_COMMIT_SHA="$DEPLOY_SHA" \
  --service api-service --environment production --skip-deploys
railway up --service api-service --environment production
```

`BUILD_COMMIT_SHA` is a persistent Railway variable. Refresh it from the exact
checked-out commit before **every** manual `railway up`, even when the variable
already exists; carrying a prior deploy's value forward makes health provenance
stale and must fail the post-deploy parity gate.

Railway uses `railway.json` → `build.builder = DOCKERFILE`. That is the only
supported production image path for this project.

The canonical public origin is `https://api.thisisatest.tech`. Railway's
generated `https://api-service-production-433c.up.railway.app` hostname is a
compatibility origin only: keep it reachable for existing integrations, but do
not publish it in customer-facing links, discovery documents, or SDK defaults.

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
| `ENABLE_DOGFOOD_TOOL` | `false` | The simulated `partner.notes.write` tool is local proof infrastructure, not a production integration. The live posture gate fails unless this is explicitly false. |
| `TRUST_MODE_ENABLED` | `true` | Shipped default; keep it |
| `ALLOW_LEGACY_UNPERMITTED_MCP` | `false` | Shipped default; keep it |
| `TRUST_SIGNING_PRIVATE_KEY_B64` | strict base64 of exactly 32 raw bytes | Required when trust mode is on in prod-like; PEM, hex, 64-byte concatenations, and double-encoded base64 are invalid |
| `STATE_BACKEND` | `postgres` | Use linked Postgres; avoid silent memory fallback |
| `DATABASE_URL` | from Railway Postgres plugin | App normalizes `postgresql://` ↔ `postgresql+asyncpg://` |
| `PUBLIC_URL` | public HTTPS API origin | `https://api.thisisatest.tech` |
| `BUILD_COMMIT_SHA` | exact 40-character deployed Git SHA | The deploy workflow sets this without triggering a separate deploy before `railway up`. Manual deploys must do the same, as shown above. |
| `PUBLIC_CONTACT_NAME` | accountable public person or entity | Launch-gated. Do not use the product name or a placeholder as the accountable identity. |
| `PUBLIC_CONTACT_EMAIL` | monitored public email address | Launch-gated. This becomes the API/OpenAPI contact only when all public contact fields are valid. |
| `PUBLIC_CONTACT_URL` | working public HTTPS booking URL | Launch-gated. Verify the booking flow manually; do not point this back to the product site. |
| `VALID_API_KEYS` | operator-set secrets | Bootstrap/admin keys only; **never** `change-me` |
| `RUN_MIGRATIONS_ON_START` | `true` (recommended; set via `railway variables`) | Entrypoint runs `alembic upgrade head` before uvicorn. App boot then **verifies** trust tables exist and **never** calls `create_all` in production-like envs. Flag + empty `DATABASE_URL` fails closed (container exits). If the DB was previously bootstrapped with `create_all` and has no `alembic_version` row, run `alembic stamp head` once before enabling this flag. |

Optional but recommended: `CORS_ORIGINS` locked to known frontends;
`REDIS_URL` only if you intend Redis rate limiting (prod-like fails closed on
Redis outage when set).

Committed `railway.json` may list **non-secret** defaults only
(`STATE_BACKEND`, `PUBLIC_URL`, `ENABLE_PROOF_SURFACES`). It must not contain
`VALID_API_KEYS` or signing material. Set `RUN_MIGRATIONS_ON_START` via
Railway variables (not committed) after confirming Alembic stamp state.

## Preflight — before you ship

`scripts/railway_preflight.py` runs two checks and exits non-zero if either
fails, so it works as a gate in a shell or in CI:

- **Migration parity** (needs `DATABASE_URL`) — compares the Alembic head in
  this tree against the `alembic_version` row in the target database. A tree
  ahead of the deployed schema is the failure that produces a 500 on the first
  request touching a new table. It also detects a `create_all`-bootstrapped DB
  with no `alembic_version` row and tells you to `alembic stamp head` once
  before enabling `RUN_MIGRATIONS_ON_START`.
- **Off-platform migration parity** (`--public-db`, needs
  `DATABASE_PUBLIC_URL`) — uses only the explicit public PostgreSQL URL. It
  never falls back to the private `DATABASE_URL`; missing, local, or
  private-looking values fail closed without printing the URL.
- **Live posture** (needs `PUBLIC_URL` or `--url`) — asserts the deployed
  service is healthy, reports `production_like=true`, has no unhealthy
  dependency, did **not** fall back to memory state, and has both
  `ENABLE_PROOF_SURFACES=false` and
  `ENABLE_DOGFOOD_TOOL=false`. Add `--expected-version` and
  `--expected-commit-sha` after deployment to require exact release identity
  from both `/health` and `/health/dependencies`; the SHA must be the full
  40-character value.

```bash
# Both checks, inside the Railway service env:
railway run python scripts/railway_preflight.py

# Schema parity only:
DATABASE_URL=postgresql://… python scripts/railway_preflight.py --db

# Schema parity from GitHub Actions or another off-platform runner:
railway run --service Postgres --environment production -- \
  python scripts/railway_preflight.py --db --public-db --strict

# Pre-deploy posture only, against the currently running release:
python scripts/railway_preflight.py --live --url "$API_URL"

# Post-deploy posture plus exact release identity:
python scripts/railway_preflight.py --live --strict --url "$API_URL" \
  --expected-version "1.3.0" \
  --expected-commit-sha "$(git rev-parse HEAD)"
```

A check whose input is absent is **skipped**, not failed; pass `--strict` to
turn a skip into a failure (what CI and the deploy workflow use). Shorthands:
`make railway-preflight` and `make railway-preflight-live`.

### Rolling retirement of legacy owner keys

Migration `025_remove_plaintext_owner_keys` scrubs `wallets.owner_key` and
`service_registry.owner_key`, but deliberately retains both empty columns and
their indexes for this release. The previously deployed worker still selects
and writes those columns, so dropping them during an overlapping Railway
deployment would break requests before that worker drains.

An old worker can write a plaintext owner credential after migration 025
performs its first scrub, or an unbound refresh token after migration 028 runs.
Therefore a deploy is incomplete until Railway reports that the new deployment
is the only active worker set and the idempotent post-deploy retirement passes:

```bash
# Run only after the old deployment has fully drained. This loads the Postgres
# service's explicit DATABASE_PUBLIC_URL and never prints it.
railway run --service Postgres --environment production -- \
  python scripts/retire_owner_keys.py
```

The command locks all three affected tables for its transaction, replaces any
late non-empty owner-key value with the empty compatibility marker, revokes any
NULL-bound refresh token, and verifies both invariants. It fails if
`DATABASE_PUBLIC_URL` or any required retirement column is missing. A later
contract migration may drop the owner-key columns only after this release can
no longer be running.

## Deploying from CI (optional)

`.github/workflows/railway-deploy.yml` is a **manual** (`workflow_dispatch`)
deploy that runs the same canonical `railway up` from a checkout of the ref you
pick. It is not a push trigger, and it does not use Railway's *Redeploy from
GitHub source* — both remain forbidden above. Before deploying it requires the
CI workflow to have concluded `success` for that exact commit (override with
`skip_ci_gate` for emergencies), then runs the live posture preflight against
the currently deployed release without requiring the new version or SHA. It
injects the resolved full commit as `BUILD_COMMIT_SHA` with `--skip-deploys`
before `railway up`. After deploying, it waits until the new deployment is the
only active worker set, re-scrubs the retained owner-key columns, and loads the
Postgres service environment so the off-platform runner can perform strict
schema parity through `DATABASE_PUBLIC_URL`. The final live check requires the
exact `pyproject.toml` version and resolved full commit SHA. This catches both a
shipped-but-unmigrated schema and a healthy response still served by the wrong
build without trying to resolve Railway's private database hostname from
GitHub Actions.

The workflow is inert until an operator adds:

| Setting | Kind | Value |
|---------|------|-------|
| `RAILWAY_TOKEN` | repo/environment **secret** | Railway project token for the target project |
| `PUBLIC_URL` | repo **variable** | Public API origin, used by the pre-deploy posture check |

Manual `railway up` from a verified working tree remains fully supported and is
still the fastest path; the workflow exists so a deploy has an auditable record
and cannot skip the migration check.

## After deploy — verify

```bash
export API_URL="${PUBLIC_URL:-https://api.thisisatest.tech}"

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
- `/health` and `/health/dependencies` report the expected application version
  and exact 40-character deployed `commit_sha`.
- `ENABLE_DOGFOOD_TOOL=false`; `/mcp/tools.json` contains no simulated dogfood
  tool ids.

### Dogfood is local-only

Do not enable `ENABLE_DOGFOOD_TOOL` in production to improve health-page optics
or simulate an upstream partner. The checked-in dogfood loop remains available
as local test evidence:

```bash
make dogfood-trust-plane
```

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
- Human approval gate (Sentinel) rollout: [`human-approval-gate.md`](human-approval-gate.md)
- Env template: [`.env.example`](../.env.example)
- Tech-debt phases: [`tech-debt-remediation-plan.md`](tech-debt-remediation-plan.md)
