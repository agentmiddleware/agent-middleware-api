# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 🔌 Standard MCP endpoint (opt-in)

- **Added `POST /mcp`** (`app/routers/mcp_standard.py`): a spec-compliant
  stateless Streamable HTTP surface for standard MCP clients — `initialize`
  with protocol-version negotiation, notifications (202), `ping`,
  `tools/list`, and `tools/call`. JSON responses only; no SSE stream, no
  sessions, so GET/DELETE answer 405. Cross-origin browser calls are
  rejected; batch requests are refused per the 2025-06-18 revision.
- **Server-minted permits keep the trust loop intact.** Standard clients
  cannot supply wallet/permit context, so `tools/call` mints a bounded,
  signed, single-tool, short-lived permit from the caller's wallet
  (`STANDARD_MCP_PERMIT_TTL_SECONDS`, default 120s) and delegates to the
  same governed invoke path as `/mcp/messages` — metering, receipts, and
  audit unchanged. Bootstrap/admin keys are refused (`-32003`): no wallet,
  no call. A client `Idempotency-Key` reuses the same auto-minted permit on
  retry, so governed replay returns the original receipt without a second
  charge.
- **Disabled by default.** `ENABLE_STANDARD_MCP_ENDPOINT=false` returns 404,
  so the surface cannot be advertised — or pass the MCP registry publish
  preflight — before an operator deliberately enables it.

### 📖 Failure semantics as a first-class spec

- **Added [docs/failure-semantics.md](docs/failure-semantics.md).** The
  complete contract for a metered call that dies mid-flight: all seven signed
  terminal outcomes (`success`, `denied`, `insufficient_funds`,
  `failed_refunded`, `delivery_uncertain`, `response_rejected`,
  `failed_unrefunded`), the crash windows the reconciler finalizes (after
  debit, after dispatch, after response, lost commit acks, effect-free), the
  replay contract, exactly-once refunds, and — deliberately — the list of
  things the system does not claim. Every behavioral row names the test that
  asserts it; all 31 cited tests exist and run in CI.
- **Crash-recovered receipts now sign byte-identical permit constraints.**
  The live invoke path normalized `aggregate_value_cap`
  (`Decimal("10.50")` → `"10.5"`) while the reconciler used `str(...)`, so a
  receipt minted during crash recovery could hash a different
  `constraints_evaluated` than a live receipt for the same permit. Both paths
  now delegate to a single `permit_constraints_snapshot` in
  `app/services/permits.py`, with a parity regression test.
- **Closed the one untested terminal outcome.** No test asserted a receipt
  with `outcome="insufficient_funds"`; `tests/test_mcp_trust.py` now proves a
  balance shortfall signs that receipt at 402/`-32004`, executes nothing,
  debits nothing, releases the reserved budget, and replays identically.

### 🔍 Observability

- **`/health/dependencies` now reports `environment` and `production_like`.**
  Whether the production trust guardrails engage depends entirely on
  `ENVIRONMENT`, which defaults to `"local"` — but no endpoint exposed the
  resolved value, so the only way to audit a running host was to read its
  secret store. A deploy that never sets the variable runs with those
  guardrails silently disabled; both fields are non-secret and make that
  externally verifiable. Additive: no existing field changed.

### 🔒 Security

- **`.env.production` now sets `ENVIRONMENT=production`.** It omitted the
  variable entirely, so `Settings.ENVIRONMENT` fell back to its `"local"`
  default and `is_production_like_environment()` returned `False` — meaning a
  host deployed from the file named `.env.production` ran with *every*
  production trust guardrail silently disabled.

### 📝 Documentation honesty

An audit of the documented setup paths found 26 confirmed defects. The README
was already accurate; almost everything else was not.

- **Removed `pip install` commands for packages that are not published.**
  `agent-middleware-api`, `agent-middleware-awi`, `langchain-agent-middleware`,
  `crewai-agent-middleware`, and `autogen-agent-middleware` are all absent from
  PyPI, yet were documented as plain installs across the four
  `framework_integrations/README.*` files, the three `wrappers/*/README.md`
  files, `docs/awi-adoption-guide.md`, and two package docstrings. Each now
  documents the local path install that actually works. The wrapper
  instructions install `./b2a_sdk` first, without which the editable install
  fails to resolve its own `b2a-sdk>=0.3.0` dependency.
- **Fixed imports of a module that does not exist.** Every
  `framework_integrations` README documented `from agent_middleware import ...`;
  the importable module is `framework_integrations`.
- **Documented startup blocks now include the signing seed.**
  `docs/golden-path.md`, `DEMO_SCRIPT.md`, and `docs/demo-instance.md` each
  started the API without `TRUST_SIGNING_PRIVATE_KEY_B64`, so the server exited
  before binding a port and every subsequent step in those guides was
  unreachable. Each now generates the seed once and reuses it, because
  rebinding a `TRUST_SIGNING_KEY_ID` to new material against a persistent
  database is rejected with `signing_key_id_public_key_mismatch`.
- **Corrected SDK constructor keywords.** `docs/agent-recipes.md` and
  `docs/agentmarket-submission.md` passed `api_url=` and `wallet_id=`, both of
  which raise `TypeError`; the parameter is `base_url=` and there is no
  `wallet_id`. All five documented constructors are now verified to construct.
- **Fixed the runnable examples.** `examples/dry_run_example.py` and
  `examples/mcp_tool_example.py` inserted the repository root onto `sys.path`,
  which shadowed the real package (sources live in `b2a_sdk/src`) and made
  every run die at `ImportError: cannot import name 'B2AClient'`.
- **Marked the aspirational parts of `docs/awi-adoption-guide.md`.** `AWIAdapter`
  does not exist anywhere in the tree. AWI sections are now labelled
  `[implemented]` or `[not implemented]`, and the guide leads with the frozen
  proof-surface status. The one adapter that does exist, `AWIFallbackAdapter`,
  now shows its real import path.
- **`examples/dry_run_example.py` now runs to completion.** It created a sponsor
  wallet, then billed every operation against the hardcoded id `sponsor-0`,
  which never exists — the server assigns ids like `spn-bde42b5c4606`. Each
  dry-run call returned `404 wallet_not_found`. The example now uses the id it
  is given, and the `@billable` functions moved inside the demo because the
  decorator captures `wallet_id` at decoration time, before any wallet exists.
  Its docstring now records the real prerequisite: the dry-run endpoints are on
  the billing router, a proof surface, so the API must run with
  `ENABLE_PROOF_SURFACES=true`.
- **`docs/demo-instance.md` no longer points at a missing compose file.**
  `docker-compose.demo.yml` is not in the repository; the guide now says to save
  the inline YAML under that name first.
- **Corrected the `VALID_API_KEYS` comment in `.env.example`.** It promised that
  an empty value yields open/development mode. Open mode also requires
  `DEBUG=true`, and the file ships `DEBUG=false`, so an empty value actually
  fails closed with `403 invalid_api_key`.

### 🐛 Reliability & fixes

- **Added the missing `scripts/core_quality_gate.sh`.**
  `scripts/repo_guardian.py` has always invoked it, but the file did not exist,
  so the guardian's "core quality gate" check failed unconditionally on every
  run and inflated its failure count. It now runs the same `ruff` and `mypy`
  checks as CI's lint job.

### 🐛 Onboarding & developer experience

- **`.env.example` now produces a server that boots.** `TRUST_MODE_ENABLED`
  defaults to true and trust mode refuses to start without signing material, so
  `TRUST_SIGNING_PRIVATE_KEY_B64` is required in *every* environment — but it
  was documented only inside a commented-out block labelled "production
  checklist". Copying the file and starting the API died with
  `SigningKeyError: trust_signing_private_key_required`. The signing seed is now
  a required top-level key with the generation command inline. The durable-state
  defaults also moved from a placeholder PostgreSQL DSN (which failed with
  `socket.gaierror` under `ENVIRONMENT=local`) to the local SQLite path the
  README documents, with the PostgreSQL block kept as commented production
  guidance.
- **Failed startups now say how to fix themselves.** Signing-key validation
  failures log an actionable `remediation` field — including the exact seed
  generation command — next to the existing error code. The
  `trust_signing_private_key_required` /
  `invalid_trust_signing_private_key` codes are unchanged, so
  `/health/dependencies` consumers are unaffected.
- **Trust gate scripts no longer depend on a specific interpreter name.**
  `scripts/trust_coverage_gate.sh` and `scripts/trust_release_gate.sh` resolved
  `python3.12` by existence alone and fell back only to `python`, skipping
  `python3`. On any machine where a bare `python3.12` is on `PATH` without the
  project's dependencies, both gates failed with `No module named pytest`. They
  now share `scripts/lib/python_env.sh`, which selects the first interpreter
  that can actually import pytest and otherwise falls back to
  `uv run --with-requirements requirements.txt`, matching every other Makefile
  target. `PYTHON` and `PYTEST` overrides still work, and CI behaviour is
  unchanged.

## [v1.2.0] - 2026-08-08

Trust-plane governance and security-hardening release. Tagged at `f365b69`, the
commit serving on the live Railway deployment (`/health/dependencies` reports
`1.2.0`). Changes since v1.1.0.

### 🔒 Security

- Removed a leaked production API key, added secret scanning, and hardened the
  live test harness (#201).
- API key rotation: runbook, generator/verifier tooling, and incident record
  (#202).
- Closed confirmed trust-plane authorization and isolation gaps (#203).
- Key revocation now contains compromises; negative-balance chargebacks are
  contained (#204).
- Removed plaintext owner keys and made owner-key retirement rolling-safe
  (#205); closed the refresh-token rollout window.
- **CORS: never pair credentialed responses with a wildcard origin** (#206).
  With `CORS_ORIGINS="*"` (the default) and `allow_credentials=True`, Starlette
  reflected the caller's `Origin` and still returned
  `Access-Control-Allow-Credentials: true`, allowing any website to make
  credentialed cross-origin reads against the trust plane. Credentials are now
  enabled only when `CORS_ORIGINS` is an explicit allowlist; a wildcard origin
  serves `Access-Control-Allow-Origin: *` with credentials disabled. Operators
  running a browser client on a separate origin must set `CORS_ORIGINS` to that
  origin's exact value. Added regression tests in `tests/test_cors_security.py`.

### 🛡️ Trust plane & governance

- Hardened governed MCP dispatch and the SDK; closed MCP transport and refund
  gaps.
- Trust-plane P0 integrity hardening; permit creation captures `subject_key_id`
  from the auth context.
- **Key rotation now revokes the old authority** (#207). Rotation previously
  left the superseded authority usable, so a rotation performed in response to a
  compromise did not actually contain it.
- **Frozen-wallet denial semantics preserved** (#208), keeping the distinct
  frozen error code rather than collapsing it into a generic denial.
- **Child-wallet TTL enforced across every governed spend path** (#209), with
  follow-up review gaps closed (#213).

### ✨ Features

- Human dashboard, observability endpoints, and accessibility tests.
- Budget percentage alerts and `/v1/me/alerts`.
- Opt-in `ENABLE_DOGFOOD_TOOL` for live `partner.notes.write`.
- Agent-discovery pointers on the marketing site, plus published agent discovery
  entrypoints (#210).

### 🌐 Site

- Canonicalized the legacy Vercel host (#211) and redirected the legacy Vercel
  root (#212).

### 🐛 Reliability & fixes

- Validate the signing key at startup and in health checks.
- Normalize tz-aware datetimes to naive UTC for PostgreSQL; keep migration
  revisions PostgreSQL-compatible.
- Fix sponsor-wallet ledger FK ordering; harden production migration boot.
- Discovery honesty: stop advertising unpublished SDK installs; gate MCP
  discovery behind the wedge.

### 📦 Dependencies

- Bumped `mcp`, `stripe`, `uvicorn`, and `redis` (Dependabot).

## [v1.0.0] - 2026-04-16

### 🚀 Major Release — Agent-Native Middleware Platform

**This release completes the full Agentic Web Interface (AWI) vision from arXiv:2506.10953v1.**

#### Phase 9: AWI Phase 9 — Paper Gap Closure

- **Agentic Web Interface (AWI)** — Stateful sessions, semantic actions, progressive representations
- **Passkey Authentication** — FIDO2/WebAuthn for high-risk action verification (`/v1/awi/passkey/*`)
- **Bidirectional DOM Bridge** — Playwright-powered browser automation for real website interaction (`/v1/awi/dom/*`)
- **RAG Memory Engine** — Semantic search over session histories with ChromaDB persistence (`/v1/awi/rag/*`)
- **Agent Discoverability** — Full discovery surfaces: `/.well-known/agent.json`, `/v1/discover`, `/mcp/tools.json`, `/llm.txt`

#### Phase 9.1: Agent Discoverability Sprint

- All Phase 9 capabilities registered in MCP tool manifest (9 new tools)
- `/.well-known/agent.json` updated with Phase 9 capabilities
- `/llm.txt` documentation includes Phase 9 examples
- Root endpoint includes `awi_phase9` service definition

#### Phase 9.2: Playwright DOM Bridge

- **Real browser execution** — `page.click()`, `page.fill()`, `page.goto()`, etc.
- DOM extraction — forms, buttons, links, navigation from live pages
- Session lifecycle — proper page/context management
- AWISessionManager routing — actions automatically route to live browser when attached

#### Phase 9.3: WebAuthn Real Verification

- **py_webauthn integration** for production-ready cryptographic verification
- Signature verification against stored public key
- Authenticator counter checking (prevents cloned credentials)
- Challenge freshness and origin validation
- Credential registration API

#### Production Hardening

- **Auth fail-safe** — Rejects requests if `VALID_API_KEYS` unset in production
- **Background cleanup** — Periodic task cleans expired WebAuthn challenges and AWI sessions
- **ChromaDB RAG persistence** — Vector storage for semantic memory

#### All Phase 9 MCP Tools

| Tool | Credits | Description |
|------|----------|-------------|
| `awi_passkey_challenge` | 1 | Generate passkey challenge |
| `awi_passkey_verify` | 2 | Verify passkey response |
| `awi_dom_bridge_session` | 5 | Create browser session |
| `awi_dom_sync` | 3 | Execute action via DOM |
| `awi_dom_state` | 2 | Get DOM state representation |
| `awi_dom_action_preview` | 2 | Preview action translation |
| `awi_memory_index` | 5 | Index session for search |
| `awi_rag_query` | 3 | Semantic search |
| `awi_session_context` | 2 | Get session context |

**Tests:** 69 Phase 9 tests passing (339 total)

---

## [v0.3.0] - 2026-04-16

### ✨ Major Features — Agentic Web Interface (AWI)

**Implements arXiv:2506.10953v1 "Build the web for agents, not agents for the web"**

- Full **Agentic Web Interface** layer (stateful AWI sessions, higher-level actions, progressive representations)
- Standardized action vocabulary (13 high-level actions: `search_and_sort`, `add_to_cart`, etc.)
- Progressive information transfer engine (`awi_representation.py`)
- Agentic task queues with concurrency limits and safety controls
- Human-in-the-loop intervention (`/v1/awi/intervene`)
- Full integration with existing MCP proxy, Behavioral Sandbox, and `/v1/ai` intelligence layer
- Behavioral Sandbox Engine (Phase 6) for real tool execution in isolated environments

**Tests:** +22 new AWI tests (total 302 passing)

**Next:** Phase 8 — External AWI Adoption Kit for website owners.

---

## [v0.2.0] - 2026-04-16

### 🚀 Major Features

- **MCP Server Generator** — `@mcp_tool` decorator, unified ServiceRegistry, dynamic MCP proxy (`/.well-known/mcp/tools.json` + JSON-RPC), standalone CLI generator
- **Dry-Run Sandbox / Shadow Ledger** — Stateful Redis-backed cost simulation with `async with b2a.simulate_session() as sim:`
- **Stripe Identity KYC** — Human sponsor verification before fiat top-ups
- **API Key Rotation** — Automatic on velocity freeze + grace period + webhooks
- **Agent Intelligence Layer** — Full `/v1/ai` (decide/heal/query/memory/learn) with multi-provider support

### Additional Features

- PostgreSQL Ledger with ACID Transactions (`app/services/agent_money.py`)

- **PostgreSQL Ledger with ACID Transactions** (`app/services/agent_money.py`)
  - Complete rewrite replacing in-memory `WalletStore` with SQLModel + PostgreSQL
  - `SELECT ... FOR UPDATE` locking for atomic operations
  - Decimal precision for all monetary calculations

- **Stripe Fiat Ingestion** (`app/services/stripe_integration.py`)
  - `/top-up/prepare` endpoint generates PaymentIntent client secret
  - Stripe webhook handler with hybrid idempotency (DB UNIQUE constraint + IntegrityError catch)
  - Automatic credit allocation on successful payment

- **Stripe Identity KYC Verification** (`app/services/kyc_service.py`, `app/routers/kyc.py`)
  - `/v1/kyc/sessions` - Create Stripe Identity verification session
  - `/v1/kyc/status/{wallet_id}` - Check KYC verification status
  - `/v1/kyc/verifications/{verification_id}` - Get verification details
  - Sponsor wallets can require KYC before allowing fiat top-ups
  - Wallet status changes to "pending_kyc" until verification completes
  - Webhook handlers for Identity verification events
  - KYC verification status enforced on top-up preparation
  - Email/Slack notifications for KYC approval/rejection

- **Agent Notifications** (`app/services/notifications.py`)
  - Email alerts via Resend API
  - Slack webhook notifications
  - Velocity freeze/unfreeze alerts

- **Agent-to-Agent Transfers** (`app/routers/billing.py`, `app/services/agent_money.py`)
  - `/transfer` endpoint for atomic credit transfers between wallets
  - Child wallet creation with spend limits and TTL
  - Swarm budget aggregation

- **Service Marketplace** (`app/services/agent_money.py`, `app/schemas/billing.py`)
  - Service registry for agent-to-agent service offerings
  - `/services` endpoints for registration and discovery
  - Service invocation with automatic credit transfer

- **Spend Velocity Monitoring** (`app/services/velocity_monitor.py`)
  - Per-wallet hourly/daily spend tracking
  - Anomaly detection using rolling average and standard deviation
  - Auto-freeze on velocity threshold breach
  - `/wallets/{wallet_id}/velocity` status endpoint

- **Webhook Router** (`app/routers/webhooks.py`)
  - `POST /webhooks/stripe` - Stripe event handler
  - `POST /webhooks/stripe/test` - Test webhook connectivity
  - `POST /webhooks/stripe/identity` - Stripe Identity webhook handler

- **Python SDK** (`b2a_sdk/`)
  - `B2AClient` async HTTP client for agent integration
  - `@monitored` decorator for usage tracking
  - `@billable` decorator for automatic credit deduction
  - `@combined` decorator for chained operations
  - Full type hints and documentation

- **MCP Server Generator** (`app/services/service_registry.py`, `app/services/mcp_generator.py`, `app/routers/mcp.py`)
  - Unified service registry for local (SDK) + persistent (DB) services
  - `@mcp_tool` decorator for auto-registering Python functions as MCP tools
  - Dynamic MCP proxy: `/.well-known/mcp/tools.json`, `/mcp/messages` JSON-RPC
  - Standalone server generator: `python -m b2a_sdk.mcp standalone --output server.py`
  - CLI tools: `generate`, `list`, `serve`, `standalone` subcommands
  - Pydantic to MCP JSON Schema conversion

- **Dry-Run Sandbox** (`app/services/shadow_ledger.py`, `b2a_sdk/`)
  - Redis-backed shadow ledger with 15-minute TTL sessions
  - Stateful cumulative simulation (balance tracking across charges)
  - `async with b2a.simulate_session()` context manager
  - `b2a.get_dry_run_estimate()` for single-shot cost checks
  - Velocity isolation: dry runs never touch VelocityMonitor

- **API Key Rotation** (`app/services/api_key_service.py`, `app/routers/api_keys.py`)
  - `POST /v1/api-keys` - Create new API key for wallet
  - `GET /v1/api-keys/{wallet_id}` - List all keys for wallet
  - `POST /v1/api-keys/rotate` - Rotate key with optional revocation
  - `DELETE /v1/api-keys/{wallet_id}/{key_id}` - Revoke specific key
  - `POST /v1/api-keys/emergency-revoke` - Emergency revocation for compromised wallets
  - `GET /v1/api-keys/{wallet_id}/logs` - Rotation audit logs
  - Keys stored hashed (SHA-256) with masked display
  - Automatic rotation on suspicious activity
  - Security alerts via Slack notifications

- **Sandbox Engine Wired to Billing** (`app/services/shadow_ledger.py`, `app/routers/billing.py`)
  - `POST /v1/billing/dry-run/session/{session_id}/commit` - Commit sandbox to real billing
  - `POST /v1/billing/dry-run/session/{session_id}/revert` - Revert and discard sandbox
  - Simulate operations in sandbox, then commit to apply charges
  - Revert to cancel without affecting real wallet
  - Full audit trail of committed vs reverted operations

- **Database Migrations** (`migrations/versions/`)
  - `001_initial.py` - Core wallet/ledger schema
  - `002_stripe_fields.py` - Stripe payment tracking fields
  - `003_velocity_monitoring.py` - Velocity monitoring fields
  - `004_kyc_verification.py` - KYC verification tables
  - `005_api_keys.py` - API key rotation tables

### Changed

- **`app/core/config.py`** - Added Stripe, notification, velocity monitoring, and KYC settings
- **`app/main.py`** - Added KYC and API key routers
- **`app/schemas/billing.py`** - Added KYCStatus, APIKeyStatus, RotationType, and sandbox schemas
- **`app/db/models.py`** - Added KYCVerificationModel, APIKeyModel, KeyRotationLogModel
- **`app/db/converters.py`** - Added kyc_status to wallet conversion
- **`app/services/shadow_ledger.py`** - Added commit_session and revert_session methods
- **`app/routers/billing.py`** - Added commit/revert endpoints for sandbox sessions
- **`tests/conftest.py`** - Added cleanup for API key tables

### Fixed

- Decimal serialization in Pydantic schemas (use float for API compatibility)
- Offset-naive vs offset-aware datetime handling in velocity monitor
- Child wallet `owner_key` made nullable (child wallets don't have owners)

### Dependencies

- Added `stripe>=6.0.0` for payment processing
- Added `mcp>=1.0.0` for MCP Server SDK (optional)
