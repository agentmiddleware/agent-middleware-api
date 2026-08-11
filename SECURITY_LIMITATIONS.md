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

High-risk AWI HTTP routes (`/v1/awi/execute`, passkey, rag index/query,
`dom/sync`) also require `X-Permit-Id` + `Idempotency-Key` and emit receipts
when invoked over HTTP. Prefer MCP for agent integrations.

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
- URL validation rejects unsafe destinations and redirects, then pins one
  validated resolved address through the later connection while preserving the
  configured HTTP Host and TLS SNI. Production should still enforce a network
  egress allowlist/proxy for the single partner origin as defense in depth.
- The upstream limit is enforced on the streamed identity-encoded HTTP body,
  including the JSON-RPC envelope, before buffering and parsing. Retained
  decoded discovery and result payloads are bounded again after validation.
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
- Set `VALID_API_KEYS` only via host secrets / Railway variables. Never commit
  real keys; never use the placeholder `change-me` in prod defaults
  (`railway.json` must not ship API keys).
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
