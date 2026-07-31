# Agent instruction plan: tech-debt remediation

**Audience:** coding agents executing this plan end-to-end or one phase at a time.  
**Product lens:** [`AGENTS.md`](../AGENTS.md) + [`WEDGE.md`](../WEDGE.md) — exactly-once MCP permits  
(`discover → authenticate → authorize → invoke → meter → receipt → audit → govern`).  
**Do not** expand proof surfaces (AWI/media/IoT/oracle/telemetry/sandbox) while doing this work.

## How to use this plan

1. Work **one phase at a time**. Open a focused PR per phase (or per P0 item if large).
2. Each phase has: goal, constraints, steps, files, tests, acceptance, stop conditions.
3. Prefer vertical slices + negative-path tests in security-critical areas (auth, permits, receipts, billing, deploy).
4. Do **not** introduce new dependencies unless justified.
5. After each phase: update this checklist (`[x]`), run targeted tests, report with AGENTS.md final-summary format.
6. Live API: `https://api-service-production-433c.up.railway.app`  
   Marketing: `https://agent-middleware-web.vercel.app`  
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

- [ ] Baseline curls documented in PR body.
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

### Live residual (not Phase 2 blockers; park for later phases)

- `/mcp/tools.json` envelope still titled **"B2A Service Marketplace"** even when `tools=[]` — rename/honesty is Phase 5 docs/OpenAPI work.
- `/v1/discover` pricing/integration copy still mentions telemetry/comms/`awi_adoption` — Phase 5 wedge honesty.
- OpenAPI `servers` still lists `http://localhost:8000` alongside production `PUBLIC_URL` (expected dual-server; Phase 3 posture can document).
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

- [ ] Written single deploy SOP.
- [ ] No committed default API key `change-me` for prod.
- [ ] At least one CI path mirrors production trust flags.

---

## Phase 4 — P1: Migrations on start + reduce create_all reliance

**Goal:** Prod schema comes from Alembic; boot does not paper over missing migrations.

### Steps

1. Read `app/db/database.py` `init_db` / `create_all` and `RUN_MIGRATIONS_ON_START`.
2. Production-like: run migrations on start (or fail if pending); avoid `create_all` for prod.
3. Keep `create_all` only for ephemeral test SQLite if required — document.
4. Test: migration path on empty DB creates permit/receipt/idempotency tables.

### Acceptance

- [ ] Prod path uses migrations.
- [ ] Docs match code (`SECURITY_LIMITATIONS.md`).

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

- [ ] No primary docs claim “full agent middleware platform.”
- [ ] agent.json documentation URLs resolve or are removed.

---

## Phase 6 — P2: Scaffolding freeze hygiene

**Goal:** Make freeze explicit so future agents don’t expand stubs.

### Steps

1. Add `docs/PROOF_SURFACES.md` (or section in WEDGE): list `PROOF_SURFACE_ROUTERS`, default “do not expand.”
2. Mark stub modules with module docstring `PROOF SURFACE — frozen`.
3. Leave blob S3, CoAP, mock embeddings, LLM mock as accept/freeze — no feature work.
4. Consider moving `kyc` / `planner` out of `CORE_TRUST_ROUTERS` only with product approval (separate PR).

### Acceptance

- [ ] Freeze list exists and is linked from `WEDGE.md`.

---

## Phase 7 — Optional follow-ons (out of core debt plan)

Only if requested after Phases 1–5:

- Absolute `canonical_api` in API `agent.json` from `PUBLIC_URL`.
- Design-partner API key bootstrap (documented gated flow).
- Operator analytics export over wallet/audit/ledger.
- Brand rename (drop provisional PERMIT).
- Link GitHub ↔ Vercel for `agent-middleware-web` (root directory `site`).

---

## Execution order (checklist for the orchestrating agent)

```text
[ ] Phase 0  Baseline (health endpoint confirmed; curls still for PR body)
[x] Phase 1  Durable state + URL normalize     ← complete (live verify OK on Railway after #178 / c5811ea)
[x] Phase 2  Gate MCP tools + llm.txt          ← complete (live verify OK on Railway after #180 / 5d547a6 via railway up)
[ ] Phase 3  Deploy posture + image SOP
[ ] Phase 4  Migrations
[ ] Phase 5  Docs / OpenAPI / registry
[ ] Phase 6  Freeze hygiene
[ ] Phase 7  Optional (only if asked)
```

### PR naming convention

- `fix/durable-state-url-normalize`
- `fix/mcp-discovery-wedge-gate`
- `fix/railway-deploy-posture`
- `fix/migrations-prod-boot`
- `docs/wedge-honesty-pass`
- `chore/freeze-proof-surfaces`

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

1. Live Railway: no durable_state memory fallback under production config.  
2. Live `/mcp/tools.json` with proof surfaces off does not list AWI/marketplace stubs.  
3. Live `/llm.txt` uses public API base and wedge bootstrap.  
4. One documented deploy path; no `change-me` prod key in repo defaults.  
5. Docs/OpenAPI match `WEDGE.md`.  
6. Proof surfaces explicitly frozen.

When all are true, mark this plan complete in a final PR that only checks the boxes above (no new features).
