# Security Limitations

This repository is not yet compliance-grade autonomous economic actor
infrastructure.

## Current Trust Boundary

The implemented trust boundary is governed MCP tool invocation. Other modules
are proof surfaces unless they consume the same permit, receipt, idempotency,
and audit-chain primitives.

The remote pilot supports one operator-configured HTTPS Streamable HTTP MCP
origin and one exact tool. Wallet checks provide application-layer isolation;
there is no row-level-security or public multi-tenant security claim.

The supported design-partner deployment is one vendor-managed Railway project
per customer, with dedicated API, PostgreSQL, Redis, domain, signing material,
and administrator credentials. It is restricted to synthetic or redacted,
low-sensitivity data: PHI, PCI data, regulated production records, and
sensitive tool arguments are out of scope. Shared SaaS, customer-VPC/BYOC, and
customer-operated on-premises deployments are not supported in this pilot.

High-risk AWI HTTP routes (`/v1/awi/execute`, passkey, rag index/query,
`dom/sync`) also require `X-Permit-Id` + `Idempotency-Key`; successful metered
calls emit receipts. Their current abort paths do not have the durable
dispatch/charge linkage needed to mint trustworthy denial receipts, so use the
MCP gateway for portable denial evidence.

## Not Yet Solved (Deferred By Design)

Keep these out of the wedge until a design partner requires them:

- No external KMS integration is implemented.
- No settlement, dispute, or compliance reporting workflow is implemented.
- Receipt signatures can be verified offline by any third party
  (`/v1/receipts/{id}/portable` plus the unauthenticated
  `/.well-known/trust-keys.json`), but no external transparency log exists. A
  receipt proves what happened, never what did not: absence of a receipt is
  not evidence that no action occurred.
- Offline verification trusts the issuing origin for key distribution. Keys
  arrive over TLS from the same origin being audited, so a compromised origin
  can serve a key set that validates forged receipts. Out-of-band key pinning
  is not implemented.
- Audit chains are wallet-scoped, but database administrators can still delete
  rows unless append-only storage or external anchoring is added.
- Multi-protocol governed adapters beyond MCP are not implemented (MCP only).
- A timeout or disconnect after the durable dispatch checkpoint is inherently
  ambiguous. The gateway retains the debit, signs `delivery_uncertain`, never
  redispatches automatically, and requires operator/upstream reconciliation.
- Gateway exactly-once behavior does not make a remote side effect exactly
  once unless the upstream honors the forwarded idempotency key.
- The configured upstream path atomically enforces the permit's `max_credits`
  ceiling. It rejects permits carrying `max_calls_per_tool` or
  `aggregate_value_cap` before reservation or dispatch because it does not yet
  implement an atomic remote counter-and-release lifecycle for those fields.
  On the local path, `aggregate_value_cap` is a settled-receipt check, not a
  concurrent-reservation boundary; use `max_credits` for a no-overshoot total.
- URL validation rejects unsafe destinations and redirects, then pins one
  validated resolved address through the later connection while preserving the
  configured HTTP Host and TLS SNI. Production should still enforce a network
  egress allowlist/proxy for the single partner origin as defense in depth.
- The upstream limit is enforced on the streamed identity-encoded HTTP body,
  including the JSON-RPC envelope, before buffering and parsing. Retained
  decoded discovery and result payloads are bounded again after validation.
- Inbound request bodies are bounded on every route by
  `MAX_REQUEST_BODY_BYTES` (1 MiB default), refused with a 413 before the rate
  limiter or any handler buffers them. An oversized declared `Content-Length`
  is rejected without reading the body; an understated one is caught by
  measuring the stream. The opt-in MCP transports keep their own tighter caps
  (256 KiB public, 64 KiB partner). This bounds per-request memory, not
  aggregate concurrency — a request-count/connection limit at the edge is
  still the operator's job.
- No public uptime SLA, compliance scope, RTO/RPO, tenant-isolation guarantee,
  or immutable-ledger claim is made.
- Sandbox and AWI/browser automation are not production isolation boundaries.
- Auto-PR and agentic workflow automation must treat GitHub issues, PRs,
  comments, webhook bodies, tool outputs, and generated scripts as untrusted.

## Required Production Posture

Operator deploy path and variable checklist:
[`docs/deploy-railway.md`](docs/deploy-railway.md) (`railway up` from this
repo; do not Redeploy from GitHub source).

- `TRUST_MODE_ENABLED=true` and `ALLOW_LEGACY_UNPERMITTED_MCP=false` are the
  shipped defaults. A production-like environment cannot boot under any
  permissive combination — `app.core.trust_mode.validate_trust_mode_guardrails`
  refuses to start. Local/dev/test deployments that need legacy behavior must
  set both env vars explicitly; the startup log emits a `trust_mode_permissive`
  warning so the opt-out is loud.
- Configure `TRUST_SIGNING_PRIVATE_KEY_B64` from a secret manager or KMS-backed
  runtime injection.
- Production-like boots also refuse `DEBUG=true`, `WEBAUTHN_ALLOW_MOCK=true`,
  and `ENABLE_PROOF_SURFACES=true`. Set `ENABLE_PROOF_SURFACES=false` so only
  core trust routers and MCP are mounted. Leave proof surfaces frozen unless a
  partner demo explicitly needs them.
- Set `PUBLIC_URL` to the public HTTPS API origin (Railway host or custom
  domain). Agents and `/llm.txt` use it; do not leave production pointing at
  localhost.
- Set `VALID_API_KEYS` only via host secrets / Railway service variables. The
  API-only [`.railway/railway.ts`](.railway/railway.ts) graph preserves the key
  name without owning or exposing its value; every configured API key uses
  `preserve()`. Never commit real keys or use the placeholder `change-me` in
  production.
- Disable or isolate proof surfaces that execute code, drive browsers, generate
  patches, crawl external URLs, or touch third-party systems.
- When `REDIS_URL` is set, production-like environments fail closed on Redis
  rate-limiter outage (HTTP 503) instead of silently using per-process memory.
  `/health/dependencies` exposes `runtime_degradation` when any configured
  backend has fallen back to in-memory.
- All Phase 9 AWI MCP tools always require signed permits (`requirePermit` in
  `/mcp/tools.json`), even if legacy unpermitted MCP is enabled. Those stubs
  are not wedge product; Phase 2 drops them from discovery when proof
  surfaces are off — see partner inventory note in
  [`DESIGN_PARTNER_GUIDE.md`](DESIGN_PARTNER_GUIDE.md#mcp-discovery-gate-phase-2).
- Run migrations (`alembic upgrade head` or `RUN_MIGRATIONS_ON_START=true` on
  the Docker entrypoint) instead of relying on
  `SQLModel.metadata.create_all`. Production-like boots skip `create_all`,
  verify required trust tables, and fail closed if the schema is missing.
  `create_all` remains only for ephemeral non-production SQLite (tests/local).
- Keep CI trust invariant tests required before merge. CI also runs a
  `production_trust` subset with production-like trust flags.

## CORS Posture

The default `CORS_ORIGINS=*` is a deliberate decision, not an oversight:

- Every authenticated route takes explicit header credentials (`X-API-Key`
  or `Authorization: Bearer`), never cookies or other ambient browser
  credentials, so there is nothing a cross-origin page can ride.
- `app.main.add_cors_middleware` refuses to pair a wildcard with
  credentialed CORS: under `*`, `Access-Control-Allow-Credentials` is never
  emitted. An explicit origin list is required before credentialed
  cross-origin requests are possible at all.
- What the wildcard actually grants is cross-origin *reads of public
  discovery surfaces* (`/.well-known/*`, `/health*`, `/llms.txt`,
  `/openapi.json`) — the same material any non-browser client already gets —
  which is standard posture for a public, header-authenticated API.
- The one route that is unauthenticated yet returns a secret
  (`/v1/dev-keys/self-provision`, local-only) independently rejects
  cross-origin browser calls by `Origin` check, and production-like
  environments refuse to boot with it enabled.

Operators who put a credentialed browser app in front of this API must set
`CORS_ORIGINS` to an explicit comma-separated origin list. Startup logs
`cors_wildcard_active` whenever the wildcard posture is in effect.

## One Auth Story, One Invoke Story (Dormant Surfaces)

The wedge contract is **send the API key** (`X-API-Key`). Surfaces that told
a second story are unmounted in production and absent from the public
OpenAPI contract (they mount only with `ENABLE_PROOF_SURFACES=true`, which
production-like boots refuse):

- `/v1/auth/token|refresh|revoke` (JWT exchange) — `app.core.auth` still
  *validates* Bearer JWTs, but nothing can mint one while the router is
  unmounted, so the key header is the only production auth path.
- `/v1/kyc/*` (Stripe Identity), `/v1/planner/optimize`, and the billing
  expansion surfaces (child/swarm wallets, transfers, top-ups, marketplace,
  velocity status, dry-run sandbox) — real code, dormant demand; see
  `DORMANT_TRUST_ROUTERS` in `app/main.py`.
- `/v1/webhooks/stripe*` mount only when Stripe is actually configured.
- `/v1/dev-keys/self-provision` stays runtime-gated by its own flag and is
  advertised in the schema only when that flag is on (never in production).

The legacy invoke entry points `POST /mcp/messages` and
`POST /mcp/tools/{id}/invoke` remain mounted for existing clients and the
local proof scripts but are marked `deprecated` in the spec; the standard
MCP Streamable HTTP endpoint at `POST /mcp` is the supported path. All entry
points run the same governed permit→meter→receipt path.

## Public Health Reporting

With proof surfaces unmounted, the unauthenticated `/health/dependencies`
payload reports only what the wedge runs on (postgres, redis, signing key,
upstream MCP, version + commit SHA, environment posture). Per-service
simulation flags and proof-surface dependency probes are not published
there; they appear in the startup log (`phase="runtime_posture"`) and on
instances that mount proof surfaces, where they describe live routes.
