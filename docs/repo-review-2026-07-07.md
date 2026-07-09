# Repo Review — 2026-07-07

Scope: full-repo review against the framework in `AGENTS.md` (core trust loop,
reality levels, security-critical areas) and the wedge defined in `WEDGE.md`
and `README.md`. This is an analysis document, not a code change — no
application code was modified.

Reality levels used below follow `AGENTS.md`: verified, partially verified,
not verified, stubbed, demo-only, misleading, contradicted, too early to tell.

## 1. Core trust spine (permits → invoke → idempotency → ledger → receipts → audit)

The claimed spine is real in substance, but two structural claims in the
docs don't hold up:

- **Ed25519 signing, revocation, permit scoping — verified.**
  `app/services/signing_keys.py` uses real `cryptography` Ed25519 keys, not a
  stub. `PermitService.validate_for_action` (`app/services/permits.py:207`)
  re-reads permit status on every call and denies non-`active` permits;
  `scripts/red_team_trust_plane.py` exercises revoked/expired/tampered/
  out-of-scope/over-budget cases end-to-end and asserts zero ledger debits.
- **Audit chain — verified as a real hash chain**, not just a signed log.
  `app/services/audit_chain.py` chains `previous_hash` → `chain_hash` per
  wallet with a serialized head row, and `tests/test_audit_chain.py` covers
  both tamper detection and concurrent-append fork prevention.
- **"Core depends only inward" — misleading.** `tests/test_trust_boundary.py`
  only inspects module-level imports and documents that function-body
  imports are deliberately excluded. `app/trust/adapters.py`'s
  `McpGovernedAdapter.invoke()` imports `app.routers.mcp._execute_registered_tool`
  from inside a function — exactly the pattern the test can't see. More
  importantly, the ~500-line governed-invocation pipeline (permit check →
  policy → budget reserve → charge → execute → receipt → audit) actually
  lives in `app/routers/mcp.py`, not in `app/trust/`. The trust package is a
  thin facade around it, not the self-contained "frozen spine" the README
  describes.
- **Atomicity across charge → receipt → audit → idempotency-complete —
  contradicted.** These are four-to-five independent commits with no
  outbox/saga. A crash between the wallet-charge commit and the receipt
  commit leaves a debited wallet with no receipt, and the idempotency record
  stuck in `IdempotencyInProgressError` permanently (`app/services/
  idempotency.py:64`) with no repair path. Only permit *budget* drift is
  reconciled (`permits.py:257` `reconcile_budgets`); receipt/ledger
  completeness is not.
- **`IdempotencyService.begin()` — partially verified.** The DB-level
  `UniqueConstraint(wallet_id, endpoint, idempotency_key)`
  (`app/db/models.py:781`) genuinely prevents a duplicate charge from
  committing, but `begin()` does SELECT-then-INSERT with no `try/except`
  around the commit — a real race between two identical concurrent requests
  surfaces as an unhandled `IntegrityError` (500) on the loser instead of the
  documented idempotent-replay response. No test exercises true concurrency
  here (the red-team script is sequential).
- The permit `nonce` field is signed but its only DB constraint,
  `UniqueConstraint(permit_id, nonce)`, is redundant with the `permit_id`
  primary key — cosmetic, not a functioning anti-replay check.

## 2. Auth, tenant isolation, secrets

- **Cross-tenant IDOR in KYC — verified, most severe finding in this
  review.** `app/routers/kyc.py` (`create_kyc_session`, `get_kyc_status`,
  `get_verification_details`) depends only on `verify_api_key` and never
  calls `require_wallet_access`. `wallet_id` comes straight from the
  client-supplied body/path, so any valid API key can read or act on another
  wallet's KYC status. Every other router that touches wallet data (e.g.
  `app/routers/api_keys.py`) calls `auth.require_wallet_access(wallet_id)`
  first — `kyc.py` is the outlier and should be fixed before this is exposed
  to more than one tenant.
- **`app/core/tenant_validation.py` is dead code.** Nothing outside the
  module imports it. Real enforcement lives in `AuthContext
  .require_wallet_access()` (`app/core/auth.py:32`), applied inconsistently
  (present in `api_keys.py`, absent in `kyc.py`). This module should be
  deleted or actually wired in — right now it reads as isolation coverage
  that doesn't exist.
- **`VALID_API_KEYS` bootstrap admin list — verified, by-design, high blast
  radius.** A match sets `is_bootstrap_admin=True` and short-circuits
  wallet-ownership checks. One leaked key impersonates every tenant. Fine as
  a documented "trusted ops" credential, but it has no independent rotation,
  scoping, or audit trail vs. DB-backed keys.
- Key/hash comparisons (`api_key_service.py:260`, `auth.py:94`) use `!=`/`in`
  instead of `secrets.compare_digest` — low practical exploitability but
  should be constant-time on principle.
- KYC (Stripe Identity) and WebAuthn are **real integrations**, not stubs —
  webhook signatures are verified, and WebAuthn fails closed if the library
  is missing unless a mock flag is explicitly set.
- No SQL injection, no hardcoded prod secrets, no `eval`/`os.system`/
  `pickle.loads` outside the explicitly gated (and disabled-by-default)
  host-Python sandbox. `.env.production` is committed but contains only
  placeholder values — still bad hygiene to commit at all.

## 3. Billing / metering integrity

- Money is `Decimal` end-to-end in the DB layer (`app/db/models.py`); public
  schemas expose `float` for compatibility but always pair it with an
  `_exact` Decimal-string field. No float-precision bug found.
- `AgentMoney.charge()`/`transfer()` lock wallet rows with `SELECT ... FOR
  UPDATE` inside one transaction, including budget/cap checks — genuinely
  race-safe for balance.
- **`velocity_monitor.check_and_record_charge()` commits in its own
  transaction, separately from the charge it precedes.** If the charge then
  fails (insufficient balance, cap, daily limit), the hourly/daily spend
  counters are already committed with no matching debit — an accounting
  desync, not fund loss.
- **`POST /v1/billing/charge` and legacy/ungoverned MCP calls have no
  idempotency-key parameter at all** — idempotency is only enforced for
  governed MCP invokes with a permit. A client retry against the direct
  billing endpoint double-charges. This directly contradicts the required
  test in `app/services/AGENTS.md` ("retry does not double-charge").
- Stripe integration is real (actual SDK calls, real webhook signature
  verification via `stripe.Webhook.construct_event`).

## 4. Tests, CI, migrations, deployment

- Test scale (18.4k lines / 694 functions) roughly matches the README's "670
  passing" badge once you account for `@pytest.mark.proof` tests excluded
  from the default `make test` run. Sampled tests are substantively good:
  cross-tenant isolation, tamper detection, revoked/expired permit denial,
  and Stripe webhook idempotency are all exercised with real assertions, not
  mock-echoes.
- `make prove-trust-plane` / `agent-ops-war-room` / `trust-coverage-gate` are
  real, assertion-based scripts (not print-and-exit demos) and CI runs them.
- **Static analysis is largely decorative.** `ruff.toml` selects `["E501"]`
  then immediately ignores it — zero real lint rules run in CI despite a
  green check. `mypy.ini` disables the error codes that catch real bugs
  (`arg-type`, `attr-defined`, `call-arg`, `union-attr`, …) and skips
  untyped function bodies.
- `tests/test_migrations.py` only upgrades an **empty** database; no
  migration is tested against populated tables, so a future unsafe schema
  change wouldn't be caught in CI. The migrations themselves look safe today
  (drops only in `downgrade()`, new non-null columns carry `server_default`).
- Dockerfile has no `USER` directive (runs as root). `docker-compose.prod
  .yml` publishes Postgres/Redis/MQTT directly to the host and defaults
  `POSTGRES_PASSWORD` to `changeme_in_production` if unset.
- No branch-protection evidence is checkable from the repo itself, so it's
  unclear whether the (otherwise good) CI gates actually block merges.

## 5. Feature sprawl vs. the stated wedge

`WEDGE.md` is explicit that AWI, oracle, media, content factory, IoT,
red-team, RTaaS, telemetry, and sandbox are "proof surfaces" that should
consume the same permit/receipt/idempotency/audit primitives as the core —
otherwise they're sprawl. Grepping every proof-surface file for
`app.trust.*` / permit / receipt / idempotency imports:

- **Zero proof surfaces call permits, receipts, or idempotency.** The only
  trust-plane contact anywhere outside the core routers is a single
  best-effort audit-log call in `awi_session.py:497`, and an
  ownership-only (no permit/budget/scope) `governance.py` check used by the
  sandbox routers. Everything else — oracle, content factory, IoT bridge,
  red team, RTaaS, telemetry, agent comms — persists to its own private DB
  models with no reference to `WalletModel`/`PermitModel`/`ReceiptModel`.
- `genesis.py` and `launch_sequence.py` have **zero `app.*` imports** —
  self-described narrative simulations ("Genesis Agent — The Meta-Launch")
  with no database or trust-plane connection at all. `dashboard.py` has no
  DB queries and its own docstring calls it "the investor demo in an API
  call."
- This matches what `docs/simulations-inventory.md` already discloses
  (8 runtime pillars flagged `SIMULATION_MODE_*=True`), so the repo is not
  hiding this — but the gap between "proof surface" framing and "wired into
  the control plane" is larger than the docs suggest, since the wiring is
  effectively absent rather than partial.

**Freeze/delete candidates, ranked:**
1. `genesis.py` / `launch_sequence.py` / `dashboard.py` (~1,700 LOC) —
   no DB or trust-plane connectivity, explicitly narrative/demo.
2. Media + IoT + Telemetry (~2,900 LOC) — standalone demos, no trust-plane
   calls, no evidence of a real external integration.
3. Oracle + broadcast (~1,970 LOC) — real DB-backed but fully parallel to
   the wedge.
4. Content factory (~1,800 LOC) — largest single proof surface, no
   trust-plane linkage.
5. Red team + RTaaS (~1,920 LOC) — overlapping security-scanning models,
   neither wired to the wedge.

## Final Summary

**Files changed:** `docs/repo-review-2026-07-07.md` (this document only —
no application code touched).

**What changed:** Added a full-repo review against `AGENTS.md`'s framework,
covering the trust-plane spine, auth/tenant isolation, billing integrity,
test/CI/infra quality, and feature sprawl vs. the stated wedge.

**Tests run:** None (analysis only; no code changed).

**What passed:** N/A.

**What was not tested:** This review is static analysis and code reading by
five parallel sub-agents; no findings were validated by writing or running
new reproduction tests.

**Remaining risks (highest to lowest severity):**
1. Cross-tenant IDOR in `app/routers/kyc.py` — any valid key can read/act on
   another wallet's KYC data.
2. No idempotency protection on `POST /v1/billing/charge` and ungoverned MCP
   calls — a client retry can double-charge.
3. No cross-transaction atomicity between charge, receipt, audit, and
   idempotency-completion — a crash mid-pipeline leaves a debited wallet
   with no receipt and a permanently stuck idempotency record.
4. The "core depends only inward" architectural guarantee is not actually
   enforced (function-body imports are excluded by design), and the real
   governed-invocation logic lives in `app/routers/mcp.py`, not `app/trust/`.
5. Ruff/mypy configuration makes static analysis largely a no-op in CI.
6. ~10k+ LOC of proof-surface code (AWI, oracle, media, content factory,
   IoT, red team, RTaaS, telemetry, genesis/launch/dashboard) has no wiring
   into permits/receipts/idempotency at all, contrary to the "proof surface"
   framing in `WEDGE.md`.

**Recommended next step:** Fix the KYC IDOR first (small, high-severity,
isolated change), then add idempotency-key support to
`POST /v1/billing/charge` before any additional billing feature work. Both
are narrow, testable changes consistent with `AGENTS.md`'s "vertical slice"
guidance, and both are prerequisites the roadmap in
`docs/production-beta-roadmap.md` already implies but doesn't yet check off.
