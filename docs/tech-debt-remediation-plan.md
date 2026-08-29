# Agent instruction plan: tech-debt remediation

**Audience:** coding agents executing this plan end-to-end or one phase at a time.  
**Product lens:** [`AGENTS.md`](../AGENTS.md) + [`WEDGE.md`](../WEDGE.md) — exactly-once MCP permits  
(`discover → authenticate → authorize → invoke → meter → receipt → audit → govern`).  
**Do not** expand proof surfaces (AWI/media/IoT/oracle/telemetry/sandbox) while doing this work.

## How to use this plan

> **Superseded deployment-config note (2026-08-28):** Historical
> `railway.json` references below describe the implementation used when these
> phases shipped. The current API-service configuration owner and activation
> boundary are `.railway/railway.ts` and `docs/deploy-railway.md`; the original
> phase record is intentionally unchanged.

1. Work **one phase at a time**. Open a focused PR per phase (or per P0 item if large).
2. Each phase has: goal, constraints, steps, files, tests, acceptance, stop conditions.
3. Prefer vertical slices + negative-path tests in security-critical areas (auth, permits, receipts, billing, deploy).
4. Do **not** introduce new dependencies unless justified.
5. After each phase: update this checklist (`[x]`), run targeted tests, report with AGENTS.md final-summary format.
6. Live API: `https://api.thisisatest.tech`;
   marketing: `https://www.thisisatest.tech/`.
   Prefer `railway up` from this repo — **do not** “Redeploy from GitHub source” (can roll back to an old image).

### Global freeze (entire plan)

- No new AWI/browser/media/IoT/oracle/RTaaS features.
- No “full agent platform” copy in OpenAPI, README, or registry docs.
- No Bluehost / custom domain work unless explicitly requested.
- Do not commit secrets, `.envrc`, or private keys.

---

## Phase 0 — Baseline evidence (read-only)

**Goal:** Capture current live and code state so later PRs can prove improvement.

### Steps

1. Read `WEDGE.md`, `SECURITY_LIMITATIONS.md`, `AGENTS.md`.
2. Curl live (record status + key JSON fields, redact secrets):
   - `GET /health`
   - `GET /health/ready` or `/health/dependencies` (whatever exists)
   - `GET /.well-known/agent.json`
   - `GET /mcp/tools.json` (count tools; note AWI/stub names)
   - `GET /llm.txt` (note Base URL)
3. Read code paths:
   - `app/core/durable_state.py` (`_resolve_backend`, fallback)
   - `app/core/runtime_degradation.py`
   - `app/routers/mcp.py` (`_ensure_local_mcp_tools_registered`)
   - `app/services/mcp_phase9_tools.py`
   - `app/core/config.py` (`ENABLE_PROOF_SURFACES`, `ENVIRONMENT`)
   - `app/core/trust_mode.py`
   - `railway.json`
4. Write a short baseline note in the PR description of Phase 1 (do not commit secrets).

### Acceptance

- [x] Baseline curls documented in PR body. *(captured across Phase 1–5 PR bodies / live verifies)*
- [x] Confirmed which health endpoint exposes `durable_state.fell_back_to_memory` (`GET /health/dependencies` → `runtime_degradation.durable_state`).

### Stop if

- Live API is down and you cannot distinguish config bugs from outage — fix deploy reachability first with human approval.

---

## Phase 1 — P0: Durable state + DATABASE_URL normalization

**Goal:** In production-like environments, fail closed or use a real durable backend. Never silently run “durable” as memory while advertising health OK.

### Constraints

- Touch `app/core/durable_state.py`, URL helpers, `railway.json` / docs, tests.
- Billing/permits/idempotency SQLAlchemy path and `asyncpg` KV path must agree on URL scheme.

### Steps

1. **Inventory URL consumers**
   - Find all uses of `DATABASE_URL`, `SQLITE_URL`, `STATE_BACKEND`.
   - Document: SQLAlchemy/Alembic need `postgresql+asyncpg://`; raw `asyncpg.create_pool` needs `postgresql://` (or use SQLAlchemy exclusively — prefer one normalizer).

2. **Implement URL normalization**
   - Add a small helper (e.g. `app/core/db_urls.py`) with:
     - `as_sqlalchemy_url(url) -> postgresql+asyncpg://…`
     - `as_asyncpg_url(url) -> postgresql://…`
   - Use it in `get_engine` / Alembic env / `durable_state` postgres path.
   - Unit-test both directions + idempotence.

3. **Fix backend resolution**
   - If `STATE_BACKEND=sqlite` and `SQLITE_URL` empty:
     - **Dev/test:** allow memory only when not production-like.
     - **Production-like:** refuse boot or fail health ready (align with `trust_mode.validate_*` style).
   - Prefer setting Railway to `STATE_BACKEND=postgres` (or redis if that’s the intended KV) **using existing Postgres**, not a second sqlite file, unless product explicitly wants sqlite file storage.
   - Ensure `mark_durable_state_fell_back` is set on every silent fallback; production-like should not soft-fallback for the intended backend.

4. **Railway config**
   - Update `railway.json` defaults: remove unsafe `STATE_BACKEND=sqlite` without URL; document required vars.
   - Set live Railway vars via CLI if logged in (redact in logs):
     - Align `STATE_BACKEND` with Postgres
     - Keep `ENVIRONMENT=production`, `ENABLE_PROOF_SURFACES=false`, trust signing vars
     - `RUN_MIGRATIONS_ON_START=true` if supported
   - Redeploy with `railway up` from repo root (not GitHub “source” redeploy).

5. **Verify**
   - Local tests for URL helper + durable_state resolution.
   - Live: `/health/dependencies` (or equivalent) shows `fell_back_to_memory=false` and postgres up.
   - Run `make dogfood-trust-plane-check` if local DB available; else targeted pytest for idempotency/receipts.

### Files (expected)

- `app/core/db_urls.py` (new) or equivalent
- `app/core/durable_state.py`
- `app/db/database.py` (if engine URL constructed there)
- `migrations/env.py` (if needed)
- `railway.json`, `.env.example`, `SECURITY_LIMITATIONS.md` or `docs/demo-instance.md` notes
- `tests/test_durable_state*.py` / new URL tests

### Acceptance

- [x] Production-like boot cannot silently use memory for intended postgres/sqlite-file backend.
- [x] Single DATABASE_URL works for SQLAlchemy + asyncpg consumers.
- [x] Live health shows no durable_state memory fallback (or ready fails closed). *(verified on Railway after `railway up` of #178 / `c5811ea`: `/health/dependencies` healthy, `fell_back_to_memory=false`)*
- [x] Tests for invalid/missing URL and production fail-closed.

### Stop if

- Changing STATE_BACKEND would wipe partner data without a migration plan — pause and report.

---

## Phase 2 — P0: Gate MCP discovery to the wedge

**Goal:** When `ENABLE_PROOF_SURFACES=false`, `/mcp/tools.json` and MCP invoke registration must **not** advertise Phase9 AWI / marketplace stub tools.

### Constraints

- Keep dogfood/demo ability to register local tools (`partner.notes.write`) via scripts.
- Do not break governed invoke for real registered tools.
- Discovery honesty: product vs proof_surface labels must match mount state.

### Steps

1. Read `_ensure_local_mcp_tools_registered` in `app/routers/mcp.py` and `ensure_phase9_registered` / `register_default_mcp_services` in `app/services/mcp_phase9_tools.py`.

2. **Gate registration**
   - Only call `ensure_phase9_registered()` / `register_default_mcp_services()` when `settings.ENABLE_PROOF_SURFACES` is true (or a narrower explicit flag if one exists).
   - When false: register nothing extra beyond what’s already in DB/registry from ops, **or** only trust-plane demo tools if tests require a builtin (prefer tests register their own tools).

3. **Align `GET /` and discover**
   - `app/main.py` `root()` must not list unmounted proof services as available.
   - `app/routers/discover.py` / `well_known` bootstrap: drop or mark AWI first-step when proof surfaces off.

4. **Fix `static/llm.txt`**
   - Production Base URL from `PUBLIC_URL` / `PUBLIC_BASE_URL` if the file is templated; if static, replace localhost with instruction to use `PUBLIC_URL` and document Railway URL.
   - Quick start = permit → invoke → receipt / dogfood — **not** telemetry/comms/AI.

5. **Tests**
   - With `ENABLE_PROOF_SURFACES=false`, `/mcp/tools.json` must not include `awi_*` or stub marketplace ids.
   - With `true`, existing phase9 tests still pass (or mark proof).
   - Negative: invoke of unregistered stub returns not-found / denied.

### Files (expected)

- `app/routers/mcp.py`
- `app/services/mcp_phase9_tools.py`
- `app/main.py`, `app/routers/discover.py`, well-known helpers
- `static/llm.txt`
- `tests/test_mcp_*.py`, new discovery honesty test

### Acceptance

- [x] Code: `/mcp/tools.json` omits AWI / marketplace stubs when `ENABLE_PROOF_SURFACES=false` (negative tests).
- [x] Live (after Railway deploy): tools.json is wedge-sized / no AWI stubs when proof off. *(verified 2026-07-31 after `railway up` of `main` @ `5d547a6` / deploy `639c908a`: `tools=[]`, no `awi_*`; `/.well-known/awi.json` → 404; `GET /` bootstrap drops awi; `/llm.txt` Base URL = `PUBLIC_URL`)*
- [x] `llm.txt` does not tell agents `localhost:8000` as the production base (`{{PUBLIC_URL}}` + operator instruction).
- [x] Dogfood / prove-trust-plane still green. *(local `make dogfood-trust-plane-check` + `make prove-trust-plane` after merge)*

### Partner prep (before code)

Live trust mode already runs with `ENABLE_PROOF_SURFACES=false`. Phase 2 stops advertising Phase9 AWI / marketplace-style discovery stubs; dogfood path stays `partner.notes.write`. Ask partners to inventory any dependency on those stub tool ids **before** merging the gate — see [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md#mcp-discovery-gate-phase-2).

### Stop if

- A partner still depends on a listed stub tool id after inventory — report before removing; do not silently drop their path.

### Implementation notes (code complete on this branch)

- Registration gated via `sync_proof_surface_mcp_registration()` in `app/services/mcp_phase9_tools.py`.
- `GET /`, `/v1/discover`, and well-known bootstrap drop unmounted proof advertising.
- Negative coverage: `tests/test_mcp_discovery_wedge_gate.py`.

### Live residual (not Phase 2 blockers; parked → addressed in Phase 5)

- ~~`/mcp/tools.json` envelope titled "B2A Service Marketplace"~~ → Phase 5 rename.
- ~~`/v1/discover` pricing/integration telemetry/comms/`awi_adoption`~~ → Phase 5 trust-plane copy.
- ~~OpenAPI localhost second server~~ → omitted when `ENVIRONMENT` is production-like.
- Live `partner.notes.write` absent until ops registers a real tool (dogfood is local ASGI; do not expect it on Railway).
- Phase 1 still holds: `fell_back_to_memory=false`, `STATE_BACKEND=postgres`, `ENABLE_PROOF_SURFACES=false`.

---

## Phase 3 — P0: Deploy posture + single deploy path

**Goal:** Production-like env always engages trust guardrails; one source of truth for images.

### Steps

1. **`railway.json` / docs**
   - Remove `VALID_API_KEYS=change-me` from committed defaults (or document as override-only).
   - Document required prod vars checklist (mirror `SECURITY_LIMITATIONS.md` + trust_mode).
   - Set `PUBLIC_URL` to the Railway API host.

2. **Image pinning**
   - Decide: Railway builds from Dockerfile in-repo (**current**) **or** pulls GHCR — pick one.
   - If GHCR: pin digest/semver in docs; stop recommending `:latest` as the only tag.
   - Add a short `docs/deploy-railway.md` section: “use `railway up`; do not Redeploy from GitHub source.”

3. **CI posture**
   - Add or extend a job/marker that runs a **production-like** subset with `TRUST_MODE_ENABLED=true`, `ALLOW_LEGACY_UNPERMITTED_MCP=false`, `ENABLE_PROOF_SURFACES=false` (even if default conftest stays permissive for unit speed).
   - Do not flip all tests to prod posture in one PR if too large — add a dedicated module first.

4. **Verify**
   - Fresh deploy boots; `trust_mode` does not warn permissive.
   - `ENABLE_PROOF_SURFACES=false` confirmed in agent.json / health.

### Acceptance

- [x] Written single deploy SOP. (`docs/deploy-railway.md` — Dockerfile + `railway up`; GHCR optional/offline only)
- [x] No committed default API key `change-me` for prod. (`railway.json` has no `VALID_API_KEYS`; guarded by `tests/test_production_trust_posture.py`)
- [x] At least one CI path mirrors production trust flags. (`.github/workflows/ci.yml` job `production_trust` + `@pytest.mark.production_trust`)

### Implementation notes (this phase)

- Image source of truth: **in-repo Dockerfile via `railway up`** (not GHCR `:latest`).
- `railway.json` non-secret defaults: `STATE_BACKEND=postgres`, `PUBLIC_URL`, `ENABLE_PROOF_SURFACES=false`.
- Live already had correct trust env; docs/CI/railway hygiene do **not** require a Railway redeploy unless operators want the new `ENABLE_PROOF_SURFACES=false` default synced into the service variable set.
- Live verify (2026-08-03, no redeploy): `/health/dependencies` → `enable_proof_surfaces=false`, `fell_back_to_memory=false`.

### Stop if

- Changing the image path would orphan a partner’s GHCR pull workflow without notice — document dual path, do not silently switch live.

## Phase 4 — P1: Migrations on start + reduce create_all reliance

**Goal:** Prod schema comes from Alembic; boot does not paper over missing migrations.

### Steps

1. Read `app/db/database.py` `init_db` / `create_all` and `RUN_MIGRATIONS_ON_START`.
2. Production-like: run migrations on start (or fail if pending); avoid `create_all` for prod.
3. Keep `create_all` only for ephemeral test SQLite if required — document.
4. Test: migration path on empty DB creates permit/receipt/idempotency tables.

### Acceptance

- [x] Prod path uses migrations.
- [x] Docs match code (`SECURITY_LIMITATIONS.md`).

**Shipped:** `init_db` skips `create_all` outside ephemeral non-prod SQLite;
verifies `permits` / `receipts` / `idempotency_records` and raises
`SchemaInitError` (lifespan fails closed). Entrypoint fails closed when
`RUN_MIGRATIONS_ON_START=true` without `DATABASE_URL`. Migrate-on-start stays
operator-set (not committed in `railway.json`) so a create_all-era DB is not
surprised by `upgrade` without a stamp. See `tests/test_schema_boot.py`.

---

## Phase 5 — P1: Docs / registry / OpenAPI honesty

**Goal:** Humans and agents see the same wedge.

### Steps

1. Rewrite or freeze `docs/agentmarket-listing.md` / MCP registry submission text to exactly-once permits (no AWI/RAG/sandbox as product).
2. Narrow FastAPI OpenAPI `description` / tags in `app/main.py` to trust plane.
3. README “deployment-ready” claims → accurate status + link to this plan’s remaining risks.
4. Optionally submit MCP registry **after** Phase 2 is live (honest tools list).
5. Serve static copies of `WEDGE.md` / `SECURITY_LIMITATIONS.md` at advertised paths **or** remove those links from agent.json.

### Acceptance

- [x] No primary docs claim “full agent middleware platform.”
- [x] agent.json documentation URLs resolve or are removed.

**Shipped:** MCP `/mcp/tools.json` envelope renamed off “B2A Service Marketplace”;
`/v1/discover` pricing + integration guides are trust-plane-only (AWI guide
gated); OpenAPI description narrowed and localhost server omitted in
production-like `ENVIRONMENT`; `WEDGE.md` / `SECURITY_LIMITATIONS.md` /
`DESIGN_PARTNER_GUIDE.md` served at advertised paths; agentmarket listing +
README deploy claims made honest; `/docs/index` gated to trust plane when
proof surfaces are off.

---

## Phase 6 — P2: Scaffolding freeze hygiene

**Goal:** Make freeze explicit so future agents don’t expand stubs.

### Steps

1. Add `docs/PROOF_SURFACES.md` (or section in WEDGE): list `PROOF_SURFACE_ROUTERS`, default “do not expand.”
2. Mark stub modules with module docstring `PROOF SURFACE — frozen`.
3. Leave blob S3, CoAP, mock embeddings, LLM mock as accept/freeze — no feature work.
4. Consider moving `kyc` / `planner` out of `CORE_TRUST_ROUTERS` only with product approval (separate PR).

### Acceptance

- [x] Freeze list exists and is linked from `WEDGE.md`.

**Shipped:** `docs/PROOF_SURFACES.md` lists `PROOF_SURFACE_ROUTERS` + accept/freeze
stubs; linked from `WEDGE.md`; router/stub modules carry
`PROOF SURFACE — frozen` docstrings; `kyc` / `planner` demotion deferred
(product approval). Tests: `tests/test_proof_surface_freeze.py`. Docs/comment
only — no Railway redeploy required.

---

## Phase 7 — Optional follow-ons (out of core debt plan)

Requested after Phases 1–6 (this continuation). Status:

- [x] Absolute `canonical_api` in API `agent.json` from `PUBLIC_URL`.
- [x] Design-partner API key bootstrap (documented gated flow).
- [x] Operator analytics export over wallet/audit/ledger.
- [ ] Brand rename (drop provisional PERMIT).
  **Deferred:** product decision; infra already uses `agent-middleware-*`.
  No mass rename. See `site/README.md` § Brand rename.
- [x] Link GitHub ↔ Vercel for `agent-middleware-web` (root directory `site`).
  Root Directory = `site`; GitHub `PetrefiedThunder/agent-middleware-api`
  connected (production branch `main`). Confirm first Git-triggered deploy
  still serves marketing + discovery redirects (`site/README.md`).

### Acceptance (Phase 7 slice)

- [x] `GET /.well-known/agent.json` includes absolute `canonical_api` when
      `PUBLIC_URL` is set; empty string when unset (no invented localhost).
- [x] Auth discovery declares `public_self_serve: false` + bootstrap docs path.
- [x] `/docs/partner-api-key-bootstrap.md` served; script
      `scripts/partner_api_key_bootstrap.py` exists.
- [x] `scripts/operator_analytics_export.py` exists (bootstrap-gated HTTP export).
- [x] Brand rename explicitly deferred with rationale.
- [x] Vercel↔GitHub linked with Root Directory `site` (confirm first Git deploy).

---

## Execution order (checklist for the orchestrating agent)

```text
[x] Phase 0  Baseline (health endpoint confirmed; curls captured in Phase 1–5 PR bodies)
[x] Phase 1  Durable state + URL normalize     ← complete (live verify OK on Railway after #178 / c5811ea)
[x] Phase 2  Gate MCP tools + llm.txt          ← complete (live verify OK on Railway after #180 / 5d547a6 via railway up)
[x] Phase 3  Deploy posture + image SOP        ← code/docs/CI complete (live already on railway up; redeploy optional)
[x] Phase 4  Migrations                        ← create_all gated; migrate-on-start fail-closed; schema verify at boot
[x] Phase 5  Docs / OpenAPI / registry
[x] Phase 6  Freeze hygiene                    ← docs/PROOF_SURFACES.md + markers; no redeploy
[~] Phase 7  Optional follow-ons               ← safe slice done; brand rename deferred (product)
```

### Plan status

**Core tech-debt remediation plan complete** after Phase 6 (Phases 0–6).
Phase 7 optional follow-ons: safe slice shipped (`canonical_api`, partner key
bootstrap, analytics export, Vercel Git link + `site` root). Brand rename
deferred.

### Post-plan backlog (unblocked / blocked)

| Item | Status |
|------|--------|
| Discovery honesty: stop advertising unpublished `pip install b2a-sdk` / `npm install @b2a/sdk` in `agent.json` + `/llm.txt` | Done (#191 / live after `railway up`) |
| Live dogfood tool on Railway (`partner.notes.write` / echo) | Done: opt-in `ENABLE_DOGFOOD_TOOL` (default false) registers executable `partner.notes.write`; enable on Railway after green deploy (keep `ENABLE_PROOF_SURFACES=false`) |
| Alembic stamp + `RUN_MIGRATIONS_ON_START=true` | Done (2026-08-04): live DB had trust tables + no `alembic_version` (create_all-era). Schema matched through `020`; missing `ledger_entries.stripe_event_id` (021). Stamped `020`, `alembic upgrade head` applied 021, then `RUN_MIGRATIONS_ON_START=true` + `railway up`. Live: boot healthy, `fell_back_to_memory=false`, stamp=`021_ledger_stripe_event_id`. |
| Brand rename (drop provisional PERMIT / `b2a_*`) | Blocked on product name |
| Demote `kyc` / `planner` from `CORE_TRUST_ROUTERS` | Blocked on product approval |

### PR naming convention

- `fix/durable-state-url-normalize`
- `fix/mcp-discovery-wedge-gate`
- `fix/railway-deploy-posture`
- `fix/migrations-prod-boot`
- `docs/wedge-honesty-pass`
- `chore/freeze-proof-surfaces`
- `chore/phase7-followups`

### Per-PR agent final summary (required)

- Files changed  
- What changed  
- Tests run  
- What passed  
- What was not tested  
- Remaining risks  
- Recommended next step (next phase id)

---

## Definition of done (whole plan)

1. [x] Live Railway: no durable_state memory fallback under production config.  
2. [x] Live `/mcp/tools.json` with proof surfaces off does not list AWI/marketplace stubs.  
3. [x] Live `/llm.txt` uses public API base and wedge bootstrap.  
4. [x] One documented deploy path; no `change-me` prod key in repo defaults.  
5. [x] Docs/OpenAPI match `WEDGE.md`.  
6. [x] Proof surfaces explicitly frozen. (`docs/PROOF_SURFACES.md` + module markers)

**Plan complete (core Phases 0–6).** Phase 7 optional safe slice shipped
(`canonical_api`, partner key bootstrap docs/script, analytics export script,
Vercel rootDirectory=`site` + GitHub connected). Brand rename remains a product
decision (deferred).
