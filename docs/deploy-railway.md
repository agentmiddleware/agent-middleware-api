# Railway deploy SOP (single path)

**Audience:** operators deploying the trust-plane API.  
**Product lens:** [`WEDGE.md`](../WEDGE.md) + [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md).

## Managed single-tenant compliance-evidence pilot

The supported enterprise pilot is vendor-managed single-tenant. Each customer
gets a separate Railway Enterprise project containing exactly one API service,
one PostgreSQL service, and one Redis service, plus a unique public domain,
administrator set, Ed25519 signing seed and key id, Sentinel tenant/key, and
upstream MCP bearer token. Do not reuse infrastructure, credentials, signing
material, or administrators between customers. Shared SaaS and customer-VPC
deployments are not part of this pilot. Provision through the manual
`railway up` path below; do not add Kubernetes, Helm, Terraform, or other pilot
orchestration infrastructure.

Keep PostgreSQL and Redis on Railway private networking and expose only the
FastAPI gateway. During qualification, verify in the Railway control plane
that neither data service has a public domain or TCP proxy and that the API's
runtime connection variables resolve to the private services. The optional
off-platform `--public-db` check requires public database exposure; do not use
that mode as evidence of a qualified private pilot deployment. Run schema
parity inside the deployed API container with `railway ssh` and its private
`DATABASE_URL` instead. `railway run` executes locally with injected variables
and therefore cannot resolve a private-only Railway database hostname.

Configure exactly one real public HTTPS MCP upstream and keep
`ENABLE_PROOF_SURFACES=false` and `ENABLE_DOGFOOD_TOOL=false`. `site/proof/`
is self-issued public demo material only; never publish customer evidence
there or describe it as an enterprise compliance dashboard.

This release is an agent governance and audit-evidence pilot, not a SOC 2,
HIPAA, PCI, or regulatory-compliance platform. Accept only synthetic or
redacted, low-sensitivity workloads: no PHI, PCI data, regulated production
records, secrets, or sensitive tool arguments. Arguments sent to Sentinel must
also be synthetic or redacted. The signing seed remains a customer-specific
Railway secret and is not KMS/HSM-backed custody.

Durable permits, reservations, bounded replay/results, receipts, approvals,
and audit records remain in that customer's PostgreSQL service. Do not export
them to a shared customer data store for this pilot.

Before onboarding a customer, enable provider backups and complete one
successful restore drill for that customer's PostgreSQL service. Prefer a
Railway PITR restore, which creates a sibling PostgreSQL service and leaves the
source online. An ordinary Railway volume-backup restore instead swaps the
source service to the restored volume and removes backups newer than the
selected point; use that mode only on a non-customer qualification stack or in
an approved maintenance window. Record the date, source backup, restore mode,
verification result, and operator without putting data or credentials in the
record. Make no SLA, RTO, or RPO claim until the corresponding behavior has
been measured and contractually approved.

## Canonical deploy path

**Build and ship from this repo with the in-repo Dockerfile. Production
releases are operator-run from a clean exact-SHA checkout.**

```bash
# From repository root, linked to the Railway service:
DEPLOY_SHA="$(git rev-parse HEAD)"
railway variable set BUILD_COMMIT_SHA="$DEPLOY_SHA" \
  --service api-service --environment production --skip-deploys
railway up --service api-service --environment production
```

That abbreviated command is appropriate only after the pre-deploy gates below.
For a stack that may hold customer data, follow the complete
[private operator release](#private-operator-release-required-for-customer-data)
checklist. GitHub Actions validates the candidate release but deliberately does
not deploy it or hold a Railway SSH key.

`BUILD_COMMIT_SHA` is a persistent Railway variable. Refresh it from the exact
checked-out commit before **every** manual `railway up`, even when the variable
already exists; carrying a prior deploy's value forward makes health provenance
stale and must fail the post-deploy parity gate.

Railway uses `railway.json` → `build.builder = DOCKERFILE`. That is the only
supported production image path for this project.

The canonical public origin for the existing first-party instance is
`https://api.thisisatest.tech`; a customer pilot uses its manifest's unique
domain instead. Railway's
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
- Keep secret files anywhere in the release checkout merely because Git
  ignores them. The Railway upload context is not a credential store; keep
  customer credentials in Railway variables or an external vault only.

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
| `TRUST_SIGNING_KEY_ID` | unique customer/environment key id | Must match the non-secret customer manifest; never bind a reused id to new material |
| `STATE_BACKEND` | `postgres` | Use linked Postgres; avoid silent memory fallback |
| `DATABASE_URL` | from Railway Postgres plugin | App normalizes `postgresql://` ↔ `postgresql+asyncpg://` |
| `REDIS_URL` | from the customer's private Railway Redis service | Unique per customer; do not expose Redis publicly |
| `PUBLIC_URL` | public HTTPS API origin | Customer manifest origin; `https://api.thisisatest.tech` only for the existing first-party instance |
| `BUILD_COMMIT_SHA` | exact 40-character deployed Git SHA | The deploy workflow sets this without triggering a separate deploy before `railway up`. Manual deploys must do the same, as shown above. |
| `PUBLIC_CONTACT_NAME` | accountable public person or entity | Launch-gated. Do not use the product name or a placeholder as the accountable identity. |
| `PUBLIC_CONTACT_EMAIL` | monitored public email address | Launch-gated. This becomes the API/OpenAPI contact only when all public contact fields are valid. |
| `PUBLIC_CONTACT_URL` | working public HTTPS booking URL | Launch-gated. Verify the booking flow manually; do not point this back to the product site. |
| `VALID_API_KEYS` | operator-set secrets | Bootstrap/admin keys only; **never** `change-me` |
| `MCP_UPSTREAM_URL` | one public HTTPS MCP origin | The pilot supports exactly one real upstream tool server |
| `MCP_UPSTREAM_BEARER_TOKEN` | customer-specific secret | Never put it in the manifest or committed files |
| `SENTINEL_API_URL` / `SENTINEL_API_KEY` | customer-specific Sentinel configuration | Send synthetic or redacted arguments only |
| `RUN_MIGRATIONS_ON_START` | `true` (recommended; set via `railway variables`) | Entrypoint runs `alembic upgrade head` before uvicorn. App boot then **verifies** trust tables exist and **never** calls `create_all` in production-like envs. Flag + empty `DATABASE_URL` fails closed (container exits). If the DB was previously bootstrapped with `create_all` and has no `alembic_version` row, run `alembic stamp head` once before enabling this flag. |

`REDIS_URL` is required for the managed pilot's isolated Redis service. Outside
that pilot it remains optional when Redis rate limiting is unused; a
production-like service fails closed on Redis outage whenever it is set.
`CORS_ORIGINS` should be locked to known frontends.

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
- **Customer deployment manifest** (`--manifest`) — validates the strict
  non-secret JSON record, requires its Alembic revision and commit SHA to equal
  this release checkout, and rejects tracked or ordinary untracked worktree
  changes that could make the `railway up` source differ from that SHA. It
  supplies its public URL and commit SHA to the live check and rejects a
  separately supplied URL or SHA that disagrees. The live gate also requires
  the configured signing key id: any id exposed by health must match, and
  `/.well-known/trust-keys.json` must always publish that id exactly once as an
  active Ed25519 key with valid 32-byte public material under the manifest
  URL's issuer. The SHA-256 fingerprint of that raw public key must equal the
  manifest's independently recorded fingerprint.

```bash
# Both checks for a deployment whose database is reachable from this machine:
railway run python scripts/railway_preflight.py

# Schema parity only:
DATABASE_URL=postgresql://… python scripts/railway_preflight.py --db

# Legacy off-platform parity diagnostic. This requires a temporary public
# database proxy and is not acceptable evidence for customer-data qualification:
railway run --service Postgres --environment production -- \
  python scripts/railway_preflight.py --db --public-db --strict

# Pre-deploy posture only, against the currently running release:
python scripts/railway_preflight.py --live --url "$API_URL"

# Post-deploy posture plus exact release identity:
python scripts/railway_preflight.py --live --strict --url "$API_URL" \
  --expected-version "1.3.0" \
  --expected-commit-sha "$(git rev-parse HEAD)"

# Managed single-tenant post-deploy gate; URL, commit, revision, and key id
# come from the non-secret manifest:
python scripts/railway_preflight.py --live --strict \
  --manifest /path/to/example-customer.production.json

# Managed single-tenant schema parity, run inside the deployed API container
# where private DATABASE_URL is reachable. This DB-only check intentionally
# omits --manifest because the image does not contain .git or the external
# customer operations record:
railway ssh --service api-service --environment production -- \
  python scripts/railway_preflight.py --db --strict
```

[`railway ssh`](https://docs.railway.com/cli/ssh) requires an operator SSH key
registered with Railway. Copy the exact SSH target command from the Railway
service dashboard if the local CLI is not already linked. Run the in-container
DB check and the local
manifest-bound live check as separate post-deploy gates; both must pass.

A check whose input is absent is **skipped**, not failed; pass `--strict` to
turn a skip into a failure (what CI and the deploy workflow use). Shorthands:
`make railway-preflight` and `make railway-preflight-live`.

### Private operator release (required for customer data)

Do not give GitHub Actions a Railway workspace SSH key. A project-scoped token
cannot manage Railway SSH keys, while a workspace key reaches every service in
the workspace. Keep the release operator-local and register one controlled key
only for the maintenance window.

Use Railway CLI 5.35.0 or newer. Earlier versions have known remote-command
argument/execution bugs. The sentinel below is mandatory even on a newer CLI:
an SSH command that returns zero without actually running must not approve a
release.

From a clean detached checkout of the exact commit:

```bash
set -euo pipefail

MANIFEST="${MANIFEST:?set MANIFEST to the controlled customer manifest path}"
SERVICE="api-service"
DEPLOY_SHA="$(git rev-parse HEAD)"
EXPECTED_VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
PROJECT_ID="$(jq -er '.railway_project_id' "$MANIFEST")"
ENVIRONMENT="$(jq -er '.environment' "$MANIFEST")"
API_URL="$(jq -er '.public_url' "$MANIFEST")"

test -z "$(git status --porcelain)"
test "${#DEPLOY_SHA}" -eq 40
git fetch origin main --no-tags
git merge-base --is-ancestor "$DEPLOY_SHA" origin/main

# Exact-SHA CI is a hard gate. Do not substitute a green PR-head run.
ci_conclusion="$(gh api \
  "repos/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/runs?head_sha=$DEPLOY_SHA&status=completed" \
  --jq '[.workflow_runs[] | select(.event == "push" and .conclusion != null)][0].conclusion // "none"')"
test "$ci_conclusion" = "success"

# Bind the local source, control-plane target, and currently running service to
# the same manifest before changing anything.
python scripts/railway_preflight.py --live --strict \
  --manifest "$MANIFEST" --url "$API_URL"
control_plane="$(railway status \
  --project "$PROJECT_ID" --environment "$ENVIRONMENT" --json)"
test "$(jq -r '.id' <<<"$control_plane")" = "$PROJECT_ID"
test "$(jq -r --arg environment "$ENVIRONMENT" \
  '[.environments.edges[].node | select(.name == $environment)] | length' \
  <<<"$control_plane")" -eq 1

# Refresh provenance, then deploy only this clean checkout. A unique marker
# lets the operator identify this deployment even if another release starts.
RELEASE_NONCE="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
RELEASE_MARKER="manual-exact-sha-$DEPLOY_SHA-$RELEASE_NONCE"
railway variable set BUILD_COMMIT_SHA="$DEPLOY_SHA" \
  --project "$PROJECT_ID" --service "$SERVICE" \
  --environment "$ENVIRONMENT" --skip-deploys
railway up --project "$PROJECT_ID" --service "$SERVICE" \
  --environment "$ENVIRONMENT" --ci \
  --message "$RELEASE_MARKER"

# Resolve and wait for the uniquely marked deployment just started above.
DEPLOYMENT_ID="$(railway deployment list \
  --project "$PROJECT_ID" --service "$SERVICE" \
  --environment "$ENVIRONMENT" --limit 20 --json \
  | jq -er --arg marker "$RELEASE_MARKER" \
      '[.[] | select(.meta.cliMessage == $marker)][0].id')"

for attempt in $(seq 1 60); do
  snapshot="$(railway status --project "$PROJECT_ID" \
    --environment "$ENVIRONMENT" --json)"
  ready="$(jq -r \
    --arg environment "$ENVIRONMENT" --arg service "$SERVICE" \
    --arg deployment "$DEPLOYMENT_ID" '
      ([.environments.edges[].node
        | select(.name == $environment)
        | .serviceInstances.edges[].node
        | select(.serviceName == $service)][0] // null) as $instance
      | $instance != null
        and ($instance.activeDeployments | length) == 1
        and $instance.activeDeployments[0].id == $deployment
        and $instance.activeDeployments[0].status == "SUCCESS"
        and ($instance.activeDeployments[0].instances | length) == 1
        and $instance.activeDeployments[0].instances[0].status == "RUNNING"
    ' <<<"$snapshot")"
  [ "$ready" = "true" ] && break
  [ "$attempt" -lt 60 ] || { echo "deployment did not become uniquely ready" >&2; exit 1; }
  sleep 5
done

INSTANCE_ID="$(jq -er \
  --arg environment "$ENVIRONMENT" --arg service "$SERVICE" \
  --arg deployment "$DEPLOYMENT_ID" '
    [.environments.edges[].node
      | select(.name == $environment)
      | .serviceInstances.edges[].node
      | select(.serviceName == $service)
      | .activeDeployments[]
      | select(.id == $deployment)
      | .instances[0].id][0]
  ' <<<"$snapshot")"

# Pin both private checks to that exact running instance. The post-drain scrub
# runs first; schema parity and the sentinel must then succeed in the same SSH
# invocation. Neither command prints DATABASE_URL or stored credentials.
remote_output="$(railway ssh \
  --project "$PROJECT_ID" --service "$SERVICE" \
  --environment "$ENVIRONMENT" \
  --deployment-instance "$INSTANCE_ID" -- \
  sh -c 'python scripts/retire_owner_keys.py --private-db && python scripts/railway_preflight.py --db --strict && printf "PRIVATE_RELEASE_CHECKS_OK\\n"')"
printf '%s\n' "$remote_output"
sentinel_count="$(printf '%s\n' "$remote_output" | grep -c '^PRIVATE_RELEASE_CHECKS_OK$' || true)"
test "$sentinel_count" -eq 1

# Refuse to bless the release if the selected instance stopped being the only
# active worker while the private checks ran.
post_snapshot="$(railway status --project "$PROJECT_ID" \
  --environment "$ENVIRONMENT" --json)"
post_ready="$(jq -r \
  --arg environment "$ENVIRONMENT" --arg service "$SERVICE" \
  --arg deployment "$DEPLOYMENT_ID" \
  --arg instance "$INSTANCE_ID" '
    ([.environments.edges[].node
      | select(.name == $environment)
      | .serviceInstances.edges[].node
      | select(.serviceName == $service)][0] // null) as $service_instance
    | $service_instance != null
      and ($service_instance.activeDeployments | length) == 1
      and $service_instance.activeDeployments[0].id == $deployment
      and $service_instance.activeDeployments[0].status == "SUCCESS"
      and ($service_instance.activeDeployments[0].instances | length) == 1
      and $service_instance.activeDeployments[0].instances[0].id == $instance
      and $service_instance.activeDeployments[0].instances[0].status == "RUNNING"
  ' <<<"$post_snapshot")"
test "$post_ready" = "true"

# The public service must attest the manifest's origin, signing key, source SHA,
# and this checkout's version.
python scripts/railway_preflight.py --live --strict \
  --manifest "$MANIFEST" --url "$API_URL" \
  --expected-version "$EXPECTED_VERSION"
```

Afterward, inspect application and HTTP logs for tracebacks, dependency
degradation, or unexpected 5xx responses. A failed private sentinel, schema
check, exact-SHA check, health check, or critical user flow is a rollback
trigger. Roll back by deploying the previously green exact SHA through this
same sequence; never reverse database migrations. Migrations used for a
rolling release must remain compatible with that rollback release.

### Customer operations manifest

Copy [`railway-customer-manifest.example.json`](railway-customer-manifest.example.json)
to a controlled operations location **outside the release checkout** and
replace every example value. Keeping the live manifest outside the checkout
avoids a recursive commit-identity problem and lets the clean-source guard
prove what `railway up` will upload. The manifest contains only these
non-secret fields:

- schema version, customer slug, Railway project id, environment, and region
- canonical public HTTPS origin and Ed25519 signing key id (maximum 64
  lowercase safe characters)
- lowercase SHA-256 digest of the raw 32-byte Ed25519 public key
- exact deployed 40-character Git SHA and Alembic head revision

Compute and record `signing_public_key_sha256` from the intended key material
before deployment as `sha256(raw 32-byte Ed25519 public key)`. Use the public
key output from the controlled key-generation step; the seed must never be
printed or put in the manifest. Do not populate the expected fingerprint by
copying the deployed `/.well-known/trust-keys.json` value during qualification:
that would make the verification tautological and allow the wrong deployed key
to approve itself.

Do not add database/Redis URLs, API keys, signing seeds, Sentinel keys, MCP
tokens, administrator credentials, customer data, or other secrets. Unknown
fields are rejected so the manifest cannot silently become a credential store.
The committed example's all-zero commit is a format placeholder and must never
be used for a deployment. Its public-key fingerprint is also synthetic example
data and must be replaced from the intended customer's key-generation record.

The preflight first binds the manifest's commit and revision to the local
release checkout and refuses a dirty worktree, then can remotely attest the
public URL, application commit, schema revision (when `--db` runs), and
active signing-key publication and fingerprint. It records the Railway
project id, environment, and region but cannot remotely attest those three
values without Railway control-plane API access. The private operator release
checklist therefore derives the project and environment selectors from this
manifest and validates them through Railway before deployment. A `railway up`
source build does not currently expose a stable runtime image
digest to this application, so `BUILD_COMMIT_SHA` is the attested release
identity and image digest is explicitly **not verified** for this pilot. Do not
invent or record a guessed digest.

Store a copy of the completed manifest with the deployment record and update
the expected commit and revision before every release. The preflight fails
closed if the recorded revision is stale, the live URL or commit differs, or
the active customer signing key cannot be verified.

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
# Run only after the old deployment has fully drained. Pin the command to the
# new API instance, whose DATABASE_URL reaches Postgres privately.
railway ssh --project "$PROJECT_ID" \
  --service api-service --environment production \
  --deployment-instance "$INSTANCE_ID" -- \
  python scripts/retire_owner_keys.py --private-db
```

The command locks all three affected tables for its transaction, replaces any
late non-empty owner-key value with the empty compatibility marker, revokes any
NULL-bound refresh token, and verifies both invariants. It fails if
the selected private `DATABASE_URL` is absent or not a Railway-private
PostgreSQL URL, or if any required retirement column is missing. It never falls
back to `DATABASE_PUBLIC_URL`. A later contract migration may drop the
owner-key columns only after this release can no longer be running.

## Validating a release in CI

`.github/workflows/railway-deploy.yml` is a manual, **validation-only**
`workflow_dispatch`. It checks out the selected ref, requires successful CI for
that exact commit, verifies the current production posture, and records the
candidate SHA and version. It never holds a Railway token or SSH key, changes a
variable, runs `railway up`, or connects through `DATABASE_PUBLIC_URL`.

The workflow requires:

| Setting | Kind | Value |
|---------|------|-------|
| `PUBLIC_URL` | repo **variable** | Public API origin, used by the pre-deploy posture check |

The workflow's green result means “candidate prepared,” not “deployed.” The
operator must then use the private release checklist above. This separation
keeps workspace-wide SSH authority out of GitHub while preserving exact-SHA,
post-drain credential retirement, private schema parity, and live posture
gates.

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

## Pilot qualification and rollout

Qualify every customer stack with synthetic or redacted data before onboarding:

1. Confirm the manifest against the linked Railway project, environment,
   region, unique domain, and configured signing key id; run strict schema and
   live preflight checks.
2. Confirm the API is the only public service, PostgreSQL and Redis have no
   public domain/TCP proxy, and the customer has unique database, Redis,
   administrator, signing, Sentinel, and upstream credentials.
3. Exercise the complete trust loop: provision → authenticate → permit → quote
   → approve and deny → invoke → meter → receipt → audit → offline verification
   → replay. Verify governed denials do not charge and portable evidence
   verifies with the published customer key.
4. Test cross-customer isolation from both directions: a customer-A key must be
   rejected by customer B, a customer-B key must be rejected by customer A,
   each trust-key document must omit the other customer's key id, and the
   database/signing-key identifiers must differ. Never print or copy the key
   values into the qualification record.
5. Complete and record the provider-backup restore drill. Prefer a PITR-created
   sibling and re-run the trust loop there before removing it through the
   approved Railway operator process. Do not treat an ordinary volume-backup
   restore as disposable: it replaces the source service's mounted volume and
   removes backups newer than the selected point.

Roll out first to an internal dedicated stack, then to one low-sensitivity
design partner. Stop promotion if deployment provenance, schema parity,
private data-service exposure, restore verification, denial portability,
metering integrity, signing-key publication, or cross-customer rejection fails.

Do not accept regulated production data or offer customer-VPC/BYOC until the
product has KMS/HSM signing through workload identity, enterprise SSO/RBAC,
private customer-tool connectivity, retention/deletion/legal-hold controls,
SIEM export, tested backup and disaster-recovery targets, append-only or
externally anchored audit evidence, and approved subprocessor/data-flow review.
Do not introduce shared SaaS until organization tenancy, PostgreSQL RLS,
tenant-scoped administration, per-tenant keys/upstreams, and adversarial
isolation tests exist.

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
