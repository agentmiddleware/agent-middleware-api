# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
