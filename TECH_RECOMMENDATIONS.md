# Technical Recommendations — Agent Middleware API

> **Historical snapshot (2026-08-23).** This teardown records conditions and
> recommendations observed on that date. Several items have since shipped or
> changed; use the current code, release gates, and
> `docs/30-day-customer-validation.md` for present status and priorities.

**Date:** 2026-08-23
**Basis:** External teardown (2026-08-22), re-verified against live `api.thisisatest.tech` and this repo on 2026-08-23.
**Scope:** Engineering work only. GTM/outreach items tracked separately. Sized for solo execution (~10–15 hrs/wk).

**Verified before writing this:**

- Live `/openapi.json` has 97 paths including `/v1/kyc/*`, `/v1/billing/arbitrage`, swarm, `/v1/planner/optimize`, `/v1/dev-keys/self-provision`, `/.well-known/awi.json`
- Root cause located: `kyc`, `dev_keys`, `planner` are in `CORE_TRUST_ROUTERS` (`app/main.py` ~line 540), not in the already-gated `PROOF_SURFACE_ROUTERS` block
- `/health/ready` reports mqtt `up, configured: true` while `/health/dependencies` reports iot_bridge simulation / `not_used`
- `commit_sha: null` in production; `BUILD_COMMIT_SHA` exists in `app/core/config.py:23` but defaults to empty
- Nine simulation-mode flags exposed in the unauthenticated health payload
- Both `awi_sdk/` and `b2a_sdk/` ship in the repo

---

## P0 — Correctness fixes (one evening, ~4–6 hrs total)

Cheap "production-like" credibility items. Batch them in one session.

- [ ] **Wire commit SHA into health.** `app/core/config.py:23` — make `BUILD_COMMIT_SHA` fall back to Railway's `RAILWAY_GIT_COMMIT_SHA` env var when unset (the comment at line 21 already anticipates this). *Acceptance:* production `/health/dependencies` shows the deployed SHA. *Effort:* 30 min.
- [ ] **Fix the `/health/ready` mqtt contradiction.** The ready endpoint reports mqtt `up, configured: true`; `/health/dependencies` (via the sim-aware `_check_mqtt` in `app/core/health.py:121`) reports simulation/`not_used`. Make ready derive from the same sim-aware check. *Acceptance:* both endpoints agree when `iot_bridge` is in simulation. *Effort:* 1 hr.
- [ ] **Drop the nine simulation-mode flags from unauthenticated health payloads.** `agent_comms`, `content_factory`, `human_approval`, `iot_bridge`, `media_engine`, `oracle`, `red_team`, `rtaas`, `telemetry_pm` — this is a public billboard of the frozen platform. Keep them in logs or an admin-auth'd health route. *Acceptance:* public health reports db, redis, signing key, upstream, version+SHA only. *Effort:* 1 hr.
- [ ] **Set `provider.contact` in `agent.json`.** Live manifest reports `contact_not_configured` — agents that bootstrap correctly are told the operator has no contact while the human site has it everywhere. Likely one env/config value. *Effort:* 15 min.
- [ ] **Verify and fix HEAD → 405.** Test: `curl -I https://api.thisisatest.tech/health`. Starlette auto-registers HEAD for GET routes, so if 405 is confirmed the culprit is a middleware short-circuiting on method (check the body-limit and auth middleware in `app/middleware/`). Fix at the middleware, not per-route. *Acceptance:* HEAD on any public GET returns the GET's status with no body. *Effort:* 1 hr.
- [ ] **Make CORS deliberate.** Replace `Access-Control-Allow-Origin: *` with an explicit origin list (www + dashboard), or keep `*` for the public discovery endpoints only and document the decision in SECURITY_LIMITATIONS.md. *Effort:* 30 min.

## P1 — Strip the public OpenAPI to the wedge (one weekend, ~6–10 hrs)

The mechanism already exists (`ENABLE_PROOF_SURFACES` gate, `app/main.py:586–590`). This is list surgery plus one router split — no new architecture.

- [ ] **Move `kyc`, `dev_keys`, `planner` out of `CORE_TRUST_ROUTERS`** into `PROOF_SURFACE_ROUTERS` (or a third `DORMANT_ROUTERS` group behind the same flag). Three one-line moves. Check nothing in the core permit/charge path imports them first. *Effort:* 1 hr incl. test run.
- [ ] **Split `app/routers/billing.py`.** Keep in core: sponsor/agent wallet CRUD, ledger, charge. Gate behind the flag: `/v1/billing/arbitrage`, `/v1/billing/wallets/{id}/swarm`, child-wallet creation, `/v1/billing/top-up` + `/prepare`, `/v1/billing/transfer` (decide — wedge is one debit per dispatch). *Effort:* 2–3 hrs incl. tests.
- [ ] **Mount Stripe webhooks conditionally.** `/v1/webhooks/stripe` and `/v1/webhooks/stripe/identity` should only mount when Stripe is actually configured (it is `not_configured` in production today). *Effort:* 30 min.
- [ ] **Remove `/.well-known/awi.json` from `well_known.py`.** The AWI routers are already gated; this one path leaks from core and returns a polite unmounted error anyway. Delete the route or gate it. *Effort:* 15 min.
- [ ] **Decide the legacy MCP endpoints.** `/mcp/messages` and `/mcp/tools/{id}/invoke` — either unmount in production or keep and mark `deprecated: true` in the spec. Fewer entry points is a simpler audit story. *Effort:* 1 hr.
- [ ] **Decide `/v1/auth/token`.** JWT exchange is a second auth story on a product whose documented contract is "send the API key." Gate it or document why it exists. *Effort:* 30 min.
- [ ] **Acceptance for the whole block:** production `/openapi.json` ≤ ~30 paths; `grep -Ei "kyc|arbitrage|swarm|planner|dev-keys|awi"` against the spec returns nothing; `make prove-trust-plane` green; test suite passes with `ENABLE_PROOF_SURFACES` both true and false.

## P2 — Make the proof independent (~0.5–1 day; blocked by the name decision)

- [ ] **Publish the verifier CLI to PyPI.** Verifier only — no server code — so the repo stays private while the proof becomes independently runnable. *Acceptance:* `pip install <name>` + verify the published receipt with zero emails sent.
- [ ] **Hard dependency: final product name first.** PyPI package names are permanent. Publishing `b2a-verify-receipt` before the rename mints one more alias forever. Do not publish until the name is decided.
- [ ] **Cheap key-distribution hardening.** Publish the Ed25519 public key fingerprint in a second channel (PyPI README + a GitHub release note). Doesn't fix "issuer distributes the keys," but gives a cross-check without building infrastructure.
- [ ] **Document key pinning as the default verify flow.** If the CLI supports verifying against a locally pinned key file (vs fetching `trust-keys.json` from the same origin), make that the documented default; add a `--pin-key` flag if it doesn't.

## P3 — Identity cleanup in code (with the rename, ~1 day)

- [ ] **Do NOT rename `awi-canonical-json/1` in place.** It is a signed format identifier — renaming it invalidates verification of every receipt already issued. Version it instead: verifier accepts `awi-canonical-json/1` (legacy) and `<newname>-canonical-json/2`; new receipts issue v2.
- [ ] **Change the kid via rotation, not renaming.** `railway-prod-ed25519` leaks infrastructure into the crypto identity. Rotation path: add the new neutrally-named kid to `trust-keys.json` + JWKS → activate it for signing → retain the old kid for verification indefinitely.
- [ ] **Collapse `awi_sdk/` and `b2a_sdk/` into one package** under the final name. Archive the old ones on a branch (no deletions); stop shipping both.
- [ ] **Grep acceptance:** public surfaces (site, OpenAPI, health, manifests, SDK name) contain no AWI / b2a / RegEngine strings except versioned scheme ids and the changelog.

## P4 — Conditional (build only when the trigger fires)

- [ ] **Sandbox demo key** — trigger: outreach is producing site visitors. Spec: public documented key bound to a demo wallet, small daily credit cap, auto-reset job, separate rate-limit bucket. Until then, the cheaper honest fix is removing "agent-first" claims from copy.
- [ ] **"Hashes only" data-scope enforcement** — trigger: first partner call scheduled. Receipts already carry request/response/payload hashes, not bodies. Audit whether any code path persists raw payloads (dispatch records, audit tables); if one does, add a no-persist/redaction config. Then state "we never store your payloads, only hashes" on the site — it's the under-sold feature for this exact buyer.
- [ ] **Egress allowlist on upstream dispatch** — trigger: first partner tool that isn't yours. Already noted as wanted in the deploy posture docs. Not needed while the only upstream is your own echo service.

## Do-not-build list

No hours on these until a design partner requires one in writing: KMS/HSM signing, transparency log or external anchoring, HA/multi-region, TypeScript SDK, additional framework wrappers, new routers of any kind. They stay where they already are — documented in SECURITY_LIMITATIONS.md.

## Sequencing

| Block | When | Gate |
|---|---|---|
| P0 | Next free evening | None |
| P1 | Next free weekend | None |
| P2 | After name decision | Name is final |
| P3 | Same pass as rename | Name is final |
| P4 | On trigger only | Demand signal |
