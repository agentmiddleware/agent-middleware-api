# Agent Middleware API: Governed MCP Gateway

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-v1.3.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141%2B-009688)
![License](https://img.shields.io/badge/license-MIT-blue)

> **Authorize one agent action. Charge it once. Prove what happened.**

Your agent invokes a costly tool. The request times out. Was the call dispatched? Should the agent retry? Will the retry create another debit? Can you prove who authorized the action and what the gateway observed?

Agent Middleware API is a governed MCP gateway and replay-safe transaction boundary for metered agent-to-tool actions. For a configured upstream MCP tool, one accepted idempotency key permits at most one gateway dispatch and at most one wallet debit. Replaying the same request under that key returns the original result and signed receipt; a changed request fails closed.

The claim-before-send release slice narrows that remote guarantee to a durable
fence: immediately before the network send, `prepared` becomes
`dispatch_claimed` and one nullable `dispatch_claim_hash` prevents a later
activation from acquiring the same send authority. Historical `dispatched`
rows remain treated as already sent. This is a gateway record, not proof that
the downstream effect occurred. Focused claim, reconciliation, migration, and
PostgreSQL process-kill tests cover the fence; those tests do not prove a
deployment or a downstream effect.

```text
scoped permit → governed MCP invoke → wallet charge → signed receipt
→ replay without second debit → out-of-scope denial
```

**Best fit:** platform engineering, AI infrastructure, and security teams governing one consequential internal MCP tool where a retry could create duplicate cost or an auditable side effect.

The supported design-partner deployment is vendor-managed and single-tenant. This is **not a full agent middleware platform**, payment network, IAM replacement, or compliance platform.

## Start here

| Goal | Start with |
|---|---|
| Decide whether this boundary fits your problem | [Product wedge](WEDGE.md) and [security limitations](SECURITY_LIMITATIONS.md) |
| Run the complete local trust loop | [Quickstart](docs/quickstart.md) |
| Put one real upstream MCP tool behind the gateway | [Partner first-tool runbook](docs/partner-first-tool-runbook.md) |
| Use the typed Python client or offline verifier | [Python SDK](b2a_sdk/README.md) |
| Review the security and accounting claims | [Security review kit](docs/security-review-kit.md) |
| Browse the supported documentation paths | [Documentation guide](docs/README.md) |

## Run the executable proof

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
make prove-trust-plane
```

That one command boots a local instance, walks the complete loop — discover, authenticate, authorize, invoke, meter, receipt, replay, and govern — and asserts every invariant: the call charges once, the replay returns the same receipt with no second debit, the audit chain verifies, and the out-of-scope call is denied. It exits non-zero the moment any stage's invariant breaks. Follow [docs/quickstart.md](docs/quickstart.md) to drive the loop yourself with your own keys.

## Product site and canonical API

- **Product site:** <https://www.thisisatest.tech>
- **Canonical API:** <https://api.thisisatest.tech>
- **Agent bootstrap:** <https://api.thisisatest.tech/.well-known/agent.json>

## Agent bootstrap

Fetch in this order:

1. `GET /.well-known/agent.json` — canonical agent bootstrap, product boundary, and discovery contract
2. `GET /llms.txt` (alias: `/llm.txt`) — agent-oriented prose and vocabulary
3. `GET /mcp/tools.json` — currently registered MCP tools with permit requirements and exact pricing
4. `GET /openapi.json` — formal API contract

Before assuming real side effects, check:

```bash
GET /health/dependencies
```

Inspect the JSON body: **HTTP 200 alone does not mean every dependency is ready**. Check `status`, the selected tool's dependencies, and `enable_proof_surfaces`. Instances that mount proof surfaces additionally report per-service `simulation_modes`; the production posture (`enable_proof_surfaces: false`) reports only the trust-plane wedge dependencies. Health never replaces authentication or permit checks.

## Authentication

Protected routes use the `X-API-Key` header. There is **no public self-serve key mint**. An operator provisions a wallet-scoped key with a bootstrap admin key, then transfers that key through a secure channel. See [docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md). Keys can be minted with operator-set bounds — an expiry (`expires_in_days`) and a server-enforced use cap (`max_uses`) — and rotation never widens them: a replacement key inherits the source key's expiry and remaining use budget ([docs/api-key-rotation.md](docs/api-key-rotation.md)).

### Local proof credentials

For local testing only, provision your own wallet-scoped dev key:

```bash
make quickstart
```

Then follow [docs/quickstart.md](docs/quickstart.md): mint your own key (no operator, no pre-shared secret), issue yourself a permit, invoke a governed tool, deliberately retry and overspend, verify your wallet's audit chain, and finish holding a signed receipt you verified offline.

See [docs/static-dev-api-keys.md](docs/static-dev-api-keys.md) for static bootstrap keys that never rotate (local-compatible environments only) and self-serve dev key provisioning (`POST /v1/dev-keys/self-provision`).

## What is implemented

The core loop:

```text
discover → authenticate → authorize → invoke → meter → receipt → audit → govern
```

| Trust step | Implemented behavior | Primary surface |
|---|---|---|
| **Discover** | Agent manifest, MCP tool manifest, agent-oriented prose, OpenAPI, dependency truth, and public signing keys | `/.well-known/agent.json`, `/mcp/tools.json`, `/llms.txt`, `/openapi.json`, `/health/dependencies`, `/.well-known/trust-keys.json`, `/.well-known/jwks.json` |
| **Authenticate** | Bootstrap operator keys plus database-issued wallet keys; API keys stored as hashes | `X-API-Key`, `/v1/api-keys` |
| **Authorize** | Ed25519-signed permits bound to issuer wallet, subject wallet/key, tools, scopes, budget, nonce, and expiry | `/v1/permits` |
| **Request** | An agent with no authority asks a human for a scoped, budgeted permit; the permit is minted from the reviewed terms after approval | `/v1/permit-requests` |
| **Quote** | Signed, single-use price commitments the metered charge honors, so a call's cost is known before it is committed to | `/v1/quotes` |
| **Invoke** | The governed HTTP/JSON-RPC MCP subset requires a permit and idempotency key and can dispatch one configured Streamable HTTP partner tool | `/mcp` (opt-in standard endpoint), `/mcp/messages`, `/mcp/tools/{service_id}/invoke` |
| **Meter** | Decimal wallet balances, row-locked debits, limits, ledger linkage, and replay-safe charging | `/v1/billing`, `/v1/me/*` |
| **Receipt** | Signed post-permit success, denial, and failure receipts linked to permits, idempotency records, remote dispatch attempts, ledger entries, and audit events | `/v1/receipts`, `/v1/evidence/{receipt_id}` |
| **Audit** | Per-wallet signed hash chains with concurrent append protection and verification | `/v1/audit`, `/v1/audit/verify-chain` |
| **Govern** | Policy decisions, revocation, spend boundaries, signing-key metadata, and operator repair paths | `/v1/policies`, permit revocation, `/v1/signing-keys`, refund reconciliation |

The end-to-end governed MCP path lives in [`app/routers/mcp.py`](app/routers/mcp.py). The protocol-facing trust facade is [`app/trust/`](app/trust/); MCP is currently the only live governed adapter.

## The loop proves these claims

1. **Charge-once under retry.** Replaying the same governed invoke with the same idempotency key returns the same receipt without a second gateway dispatch or wallet debit, even across the governed MCP entrypoints; changed payloads conflict.
2. **Budget over-spend containment.** A permit's `max_credits` budget is reserved with a single atomic guarded `UPDATE` — the bound is enforced in the statement's `WHERE` clause, not a read-modify-write — so concurrent invocations against one permit cannot over-spend it on any storage engine, including SQLite.
3. **Interrupted-invocation accounting.** For the configured upstream tool, one persisted chain links the idempotency record, permit reservation, ledger debit, dispatch attempt, signed receipt, and audit event. Recovery finalizes pre-claim failures or marks a missing trustworthy result after a durable send claim `delivery_uncertain`; it never redispatches that attempt. The gateway record does not prove the downstream effect.
4. **Signed offline-verifiable receipts.** Receipts are Ed25519-signed and verifiable without credentials or network access to the issuing server. Export a receipt with `GET /v1/receipts/{receipt_id}/portable`, fetch the public key set from `/.well-known/trust-keys.json` or `/.well-known/jwks.json`, and verify with the SDK verifier or any off-the-shelf JOSE tooling.
5. **Authority-before-money denial.** A request outside the permit scope, with no permit, or with an expired/revoked/tampered permit is denied with a concrete reason code before any wallet charge. When the trust plane refuses the call, a signed denial receipt proves *that* refusal.

Adversarial coverage of all five claims, enforced gate-first, lives in [`tests/test_adversarial_five_claims.py`](tests/test_adversarial_five_claims.py). CI runs the full release gate as one dedicated check (`trust_release_gate`), starting with the offline Railway IaC package and fail-closed graph contract, so configuration or trust claims cannot regress into `main` unproven.

## What this is not

From [WEDGE.md](WEDGE.md) and [SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md):

- **Not settlement.** This is an internal credit and budget ledger. It is not merchant settlement, a dispute system, or a compliance ledger.
- **Not a compliance platform.** Receipts may be one input an operator's auditor accepts; that is the operator's determination, not ours. No mappings, no certifications, no "compliance-ready."
- **Not an IAM replacement.** Wallet checks provide application-layer isolation; there is no row-level-security or public multi-tenant security claim.
- **Not universal exactly-once.** Gateway replay safety does not make a remote tool's side effect exactly once unless that tool also honors the forwarded idempotency key.
- **Not a transparency log.** Receipts can be verified offline, but there is no external transparency log. A receipt proves what happened, never what did not.
- **No public SLA.** The supported design-partner deployment is vendor-managed and single-tenant: one Railway project, API service, PostgreSQL database, Redis instance, public origin, signing key, and bootstrap-admin set per customer. Customer deployments must not share runtime services, databases, signing material, or operator credentials.

## Product boundary

The agent-action transaction boundary is the product. Broader agent features in this repository are retained as proof surfaces and are frozen unless a specific product decision brings one through the same permit, metering, receipt, and audit loop.

| Core transaction boundary | Frozen proof surfaces |
|---|---|
| Wallet-scoped API keys and tenant checks | AWI, browser, DOM, passkey, and RAG demos |
| Signed permits and revocation | Content, media, IoT, oracle, and comms demos |
| Governed MCP invocation and idempotency | Red-team, RTaaS, sandbox, telemetry, and auto-PR demos |
| Wallet metering and ledger | Simulated or partial external integrations |
| Signed receipts and evidence | Framework examples not yet shipped as packages |
| Signed wallet audit chains | Marketing/demo workloads |

Production-like deployments must set `ENABLE_PROOF_SURFACES=false`; startup refuses a production configuration that enables them. The complete inventory and unfreeze rules are in [docs/PROOF_SURFACES.md](docs/PROOF_SURFACES.md).

## Quick start: prove the trust loop

Prerequisites: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and `make`.

Install `uv` (one line, copy-paste):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone and prove:

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
make prove-trust-plane
```

The proof uses a throwaway local SQLite database and the real FastAPI routes. It asserts all of the following in one run:

1. MCP tool discovery.
2. Sponsor wallet, agent wallet, and wallet-bound key provisioning.
3. Signed permit issuance for one tool and budget.
4. Governed MCP invocation and one ledger debit.
5. Signed receipt, evidence bundle, and valid audit chain.
6. Replay returning the same receipt without a second debit or execution.
7. Out-of-scope denial without a charge.
8. Offline verification of the receipt with no credentials, including detection of an edited bundle.
9. Detection of tampered receipt and audit data.

To run the same proof without `uv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/demo_trust_plane.py --assert
```

The walkthrough and representative output are in [DEMO_SCRIPT.md](DEMO_SCRIPT.md) and [docs/demo-trust-plane-output.md](docs/demo-trust-plane-output.md).

### Operate it yourself: the 15-minute golden path

`make prove-trust-plane` proves the loop *to* you; the quickstart lets you *drive* it. One command boots a real local trust plane with self-serve key minting and one invokable governed tool:

```bash
make quickstart
```

Then follow [docs/quickstart.md](docs/quickstart.md): mint your own wallet-scoped key (no operator, no pre-shared secret), issue yourself a permit, invoke a real governed tool, deliberately try to double-charge and overspend, verify your wallet's tamper-evident audit chain with your own key, and finish holding a signed receipt you verified offline — plus a forged one the verifier rejected. Every step of that page runs in CI against a freshly booted server (`make quickstart-check`), so the documented path cannot silently rot.

### One command, whole loop, partner handoff bundle

To drive the entire loop end-to-end against a running quickstart server — and produce artifacts you can hand to someone else to verify — run:

```bash
make quickstart        # terminal 1: boots the server
make live-loop-proof   # terminal 2: drives the loop, writes the bundle
```

`live-loop-proof` walks the full core loop as a self-provisioned non-admin caller and asserts each invariant rather than only printing it: `POST /v1/permits/verify` admits the granted action and refuses a registered tool the permit does not name, the call charges the known price once, the replay returns the same receipt with no second debit, the audit chain verifies, and the out-of-scope call is denied with a signed, zero-charge receipt. It exits non-zero the moment any stage's invariant breaks.

On success it writes a handoff bundle to `data/live-loop-proof/`: the portable success and denial receipts, the issuer's public key set, a machine-readable transcript, and a `VERIFY.md` a partner engineer can follow to verify both receipts offline — no account, no credential, and no network access to the issuing server. Handing that directory to a partner engineer who runs the verifier themselves rehearses the independent-verification mechanics of the customer-validation milestone; the milestone step itself requires the receipt to come from a partner-owned agent and staging tool and be verified in the partner's environment ([docs/30-day-customer-validation.md](docs/30-day-customer-validation.md)). The command runs end to end in CI (`tests/test_quickstart_path.py`).

## Governed MCP call shape

After an operator provisions a funded wallet and key, the normal flow is:

1. Discover the tool through `/mcp/tools.json`.
2. Create a signed permit through `POST /v1/permits` with an `Idempotency-Key` header.
3. Optionally take a signed price with `POST /v1/quotes` and pass its `quote_id` in `mcpContext` to lock what the call will cost.
4. Invoke the permitted tool with the wallet, permit, and invocation idempotency key in `mcpContext`.
5. Verify the returned receipt or fetch its evidence bundle.

An agent that holds no permit can ask a human for one first with `POST /v1/permit-requests` and poll until the signed permit is minted.

```bash
curl -sS -X POST "$API_URL/mcp/messages" \
  -H "X-API-Key: $AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"id\": \"request-1\",
    \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"$TOOL_ID\",
      \"arguments\": {\"input\": \"hello\"},
      \"mcpContext\": {
        \"wallet_id\": \"$WALLET_ID\",
        \"permit_id\": \"$PERMIT_ID\",
        \"idempotency_key\": \"invoke-1\"
      }
    }
  }"
```

`POST /mcp/messages` is the project's legacy JSON-RPC transport — marked deprecated in the OpenAPI contract but fully supported, and the only JSON-RPC surface in a default local run. When the opt-in standard MCP endpoint is enabled (`ENABLE_STANDARD_MCP_ENDPOINT=true`), new integrations should prefer `POST /mcp`; both run the same governed permit → meter → receipt path.

Use [docs/golden-path.md](docs/golden-path.md) for the complete HTTP sequence and [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) to put one real internal tool behind the governed path.

## Run the API locally

The following keeps strict trust mode enabled while using local SQLite files. Generate the signing seed once for a new database, save it in the ignored `.env` file or another local secret store, and reuse it on every restart:

```bash
python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

Do not reuse these local secrets in a shared environment.

```bash
mkdir -p data
export ENVIRONMENT=local
export DATABASE_URL=sqlite+aiosqlite:///./data/local_api.db
export STATE_BACKEND=sqlite
export SQLITE_URL=./data/local_state.db
export VALID_API_KEYS=local-bootstrap-key
export TRUST_MODE_ENABLED=true
export ALLOW_LEGACY_UNPERMITTED_MCP=false
export ENABLE_PROOF_SURFACES=false
export TRUST_SIGNING_KEY_ID=local-dev-ed25519
export TRUST_SIGNING_PRIVATE_KEY_B64='<saved-base64-seed>'

uv run --with-requirements requirements.txt \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

In another shell:

```bash
curl -sS http://localhost:8000/.well-known/agent.json
curl -sS http://localhost:8000/mcp/tools.json
curl -sS http://localhost:8000/health/dependencies
```

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`. Generate the local signing key once per database and reuse the same key material with the same key ID on subsequent starts; changing material under an existing key ID is rejected to preserve historical verification.

`VALID_API_KEYS` contains bootstrap operator credentials, not agent runtime keys. There is no public self-serve key mint. An operator creates wallets and a wallet-scoped agent key, then transfers that key through a secure channel. See [docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md).

For local testing and training material that needs a credential which never rotates, use `STATIC_DEV_API_KEYS` instead: static `amw_dev_` keys that authenticate only in local-compatible environments (a production-like deployment refuses to boot with them set). Generate with `python scripts/generate_static_dev_keys.py` — see [docs/static-dev-api-keys.md](docs/static-dev-api-keys.md).

An agent working against a local instance can also mint its own wallet-scoped dev key with no pre-shared secret. Opt in with `ENABLE_DEV_KEY_SELF_PROVISION=true`, then `POST /v1/dev-keys/self-provision` provisions a sponsor wallet, an agent wallet with bounded synthetic dev credits, and a wallet-scoped key shown once — the same credential class an operator bootstrap produces, never bootstrap-admin. The route answers 404 until the flag is set, and a production-like deployment refuses to boot with it enabled. Never enable it on a shared or hosted deployment; details are in the same [docs/static-dev-api-keys.md](docs/static-dev-api-keys.md).

### Optional: connect one upstream MCP tool

Design-partner mode exposes one exact tool from one Streamable HTTP MCP server through the same permit, debit, receipt, evidence, and audit path:

```bash
export MCP_UPSTREAM_ENABLED=true
export MCP_UPSTREAM_URL=https://mcp.partner.example/mcp
export MCP_UPSTREAM_TOOL_NAME=partner.write
export MCP_UPSTREAM_PUBLIC_TOOL_ID=partner.notes.write
export MCP_UPSTREAM_BEARER_TOKEN=...       # secret manager only
export MCP_UPSTREAM_CREDITS_PER_CALL=7.5
```

On startup, the gateway discovers the exact upstream tool and refuses readiness if configuration, connectivity, or discovery validation fails. Production requires a public HTTPS URL; plain HTTP is accepted only for an explicit loopback URL in local or test environments. The gateway forwards the invocation idempotency key as MCP request metadata, but remote exactly-once behavior still depends on the upstream honoring it. Inspect `/health/dependencies` for payload-free call, dispatch-state, uncertainty, and reconciliation-backlog counts. Upstream discovery keeps the legacy numeric `creditsPerCall` annotation and adds the authoritative Decimal string `creditsPerCallExact`; clients doing budget math must prefer the exact field. See [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) for the live checklist and failure semantics.

## Core API surfaces

| Surface | Purpose | Access |
|---|---|---|
| `GET /.well-known/agent.json` | Canonical agent bootstrap and product/proof boundary | Public |
| `GET /mcp/tools.json` | Currently registered MCP tools and permit requirements | Public discovery |
| `POST /v1/api-keys` | Issue a wallet-scoped runtime key, optionally bounded by expiry (`expires_in_days`) and a server-enforced use cap (`max_uses`) | Bootstrap admin or authorized wallet |
| `POST /v1/api-keys/rotate` | Replace a wallet key with a new one that inherits its expiry and remaining use budget | Bootstrap admin or authorized wallet |
| `POST /v1/api-keys/emergency-revoke` | Revoke all keys on a wallet at once, optionally minting one bounded replacement | Bootstrap admin or authorized wallet |
| `POST /v1/permits` | Issue a scoped, signed permit | Authorized issuer wallet; idempotency required |
| `POST /v1/permit-requests` | Ask a human for authority the agent cannot mint itself | Authorized subject wallet; idempotency required |
| `GET /v1/permit-requests/{request_id}` | Poll the decision; returns the minted permit once approved | Issuer wallet, subject wallet, or admin |
| `POST /v1/quotes` | Get a signed price for one call of a tool | Authorized wallet |
| `POST /mcp` | Standard MCP Streamable HTTP endpoint (official SDK stateless transport); `tools/call` runs the governed pipeline with server-minted single-tool permits | Authentication; opt-in via `ENABLE_STANDARD_MCP_ENDPOINT=true`, default off |
| `POST /mcp/messages` | JSON-RPC MCP list/call transport (legacy; deprecated in the OpenAPI contract — new integrations should prefer the opt-in `POST /mcp`) | Authentication; permit required for governed calls |
| `GET /v1/permits` | List permits; a wallet key sees its own, an operator key sees all | Wallet key or admin |
| `GET /v1/me/permits` | Current wallet's permit view | Wallet key |
| `GET /v1/me/permit-requests` | Authority this wallet has asked a human for | Wallet key |
| `GET /v1/me/quotes` | Price commitments this wallet holds | Wallet key |
| `GET /v1/me/receipts` | Current wallet's receipt view | Wallet key |
| `GET /v1/me/audit/events` | Current wallet's audit view | Wallet key |
| `POST /v1/receipts/verify` | Verify signed receipt material | Authenticated |
| `GET /v1/receipts/{receipt_id}/portable` | Export a receipt as offline-verifiable evidence | Authorized wallet/admin |
| `GET /.well-known/trust-keys.json` | Public signing keys for offline receipt verification, with issuance/retirement metadata | Public, unauthenticated |
| `GET /.well-known/jwks.json` | The same signing keys as a standard JWK Set (RFC 7517) for JOSE tooling | Public, unauthenticated |
| `GET /v1/evidence/{receipt_id}` | Permit, dispatch, ledger, receipt, and audit evidence bundle | Authorized wallet/admin |
| `POST /v1/audit/verify-chain` | Verify a wallet audit chain | Authorized wallet/admin |
| `GET /v1/receipts/reconciliation/refunds` | Inspect failed-refund work items; a wallet key sees its own, an operator key sees all | Wallet key or bootstrap admin; the retry action stays bootstrap admin only |
| `POST /v1/billing/top-up/prepare` | Create a Stripe PaymentIntent for a sponsor wallet | Authorized sponsor wallet; dormant expansion surface — mounts only with `ENABLE_PROOF_SURFACES=true`, never in production |
| `GET /health/dependencies` | Wedge dependency truth (postgres, redis, signing key, upstream MCP, version + commit SHA); instances that mount proof surfaces also report simulation modes | Public operator check |

The generated contract at `/openapi.json` is canonical. A checked-in copy lives at [docs/openapi.json](docs/openapi.json) and is held in sync by CI.

## Security and accounting posture

### Strict production configuration

The supported Railway production posture is:

```bash
ENVIRONMENT=production
DEBUG=false
STATE_BACKEND=postgres
DATABASE_URL=postgresql+asyncpg://...
RUN_MIGRATIONS_ON_START=true            # or run `alembic upgrade head` before boot
PUBLIC_URL=https://api.example.com
CORS_ORIGINS=https://console.example.com
VALID_API_KEYS=...                    # bootstrap secrets
TRUST_MODE_ENABLED=true
ALLOW_LEGACY_UNPERMITTED_MCP=false
ENABLE_PROOF_SURFACES=false
WEBAUTHN_ALLOW_MOCK=false
TRUST_SIGNING_KEY_ID=...
TRUST_SIGNING_PRIVATE_KEY_B64=...     # base64-encoded 32-byte Ed25519 seed
```

The application refuses unsafe production combinations. It also refuses silent in-memory fallback when durable state was configured for production, and on a hosted runtime (detected through the platform-injected `RAILWAY_*` variables) it refuses to boot when `ENVIRONMENT` is unset or blank instead of silently running with local-compatible defaults. Use `alembic upgrade head` for schema changes; production startup verifies the schema instead of relying on `create_all`.

Apply the current migration head before mixed old/current workers take traffic. Migration 027 serializes the legacy JSON-RPC and REST governed-MCP endpoint identities behind one wallet/idempotency-key uniqueness boundary. Migration `037_mcp_dispatch_claim_hash` adds the nullable remote dispatch-claim fence. Its rolling and rollback requirements are in [the Railway deploy SOP](docs/deploy-railway.md#dispatch-claim-migration-and-rollback).

The supported API deployment path is the repository Dockerfile on Railway: [docs/deploy-railway.md](docs/deploy-railway.md). The static agent-first site in [`site/`](site/) is a separate marketing/discovery surface, not the API runtime.

### Managed single-tenant pilot boundary

The supported enterprise pilot is **vendor-managed and single-tenant**: one Railway project, API service, PostgreSQL database, Redis instance, public origin, signing key, and bootstrap-admin set per design partner. Customer deployments must not share runtime services, databases, signing material, or operator credentials.

This pilot accepts only synthetic or explicitly redacted, low-sensitivity workloads. It is not approved for PHI, PCI data, regulated production records, or sensitive tool arguments. The configured upstream MCP server must be one public HTTPS origin; customer-VPC/BYOC connectivity, shared multi-tenant SaaS, and an uptime or RTO/RPO commitment are not supported in this release.

The public site and `/proof/` receipt are self-issued product demonstrations. Customer evidence stays in the customer's dedicated API and database and is exported through the authenticated receipt/evidence APIs plus the offline SDK verifier.

### Billing integrity

- Credits use `Decimal` values internally and expose paired exact fields where API compatibility also requires floats.
- Charges, transfers, refunds, wallet provisioning, and Stripe settlement use database transactions and row locks where ordering matters.
- A permit's `max_credits` budget is reserved with a single atomic guarded `UPDATE` — the bound is enforced in the statement's `WHERE` clause, not a read-modify-write — so concurrent invocations against one permit cannot over-spend it on any storage engine, including SQLite, where `SELECT ... FOR UPDATE` is a silent no-op. Covered by `tests/test_permits.py::test_concurrent_reservations_never_exceed_cap`, `tests/test_governed_persistence.py::test_remote_prepare_cap_holds_under_concurrency`, and the PostgreSQL `postgres_permit_concurrency` CI job.
- On local governed tools, per-tool call caps (`max_calls_per_tool`) use an optimistic compare-and-swap on a persisted per-permit counter. The configured upstream MCP path does not yet own the matching atomic counter-and-release lifecycle, so it fails closed with `permit_constraint_unsupported_for_upstream` before reserving budget, debiting, or dispatching whenever that constraint is configured.
- `aggregate_value_cap` is evaluated from settled receipt history on the local path; it is not a concurrent-reservation boundary. The upstream path likewise fails closed when it is configured. Use `max_credits` when the required property is an atomic total authorization ceiling.
- Direct top-up is deprecated and returns `410 Gone`; a client-supplied token is not treated as proof of payment.
- Stripe webhooks are signature checked, settlement fields are validated, and event identities prevent duplicate application.
- This is an internal credit and budget ledger. It is not merchant settlement, a dispute system, or a compliance ledger.

### Remaining limits

- Signing keys are injected from environment/secret storage; an external KMS integration is not implemented.
- Receipts are verifiable, but there is no external transparency log.
- Audit chains are tamper-evident, not immutable against an administrator who can alter both the database and its chain metadata.
- MCP is the only live governed adapter; universal multi-protocol enforcement is not implemented.
- The public MCP surface is an HTTP/JSON-RPC tools subset at `/mcp/messages`, plus an opt-in standard endpoint at `POST /mcp` (`ENABLE_STANDARD_MCP_ENDPOINT`, default off) whose protocol surface — `initialize` and version negotiation, notifications, `ping`, JSON-RPC framing and errors — is served by the official MCP SDK's stateless Streamable HTTP transport (JSON responses only, no SSE stream or sessions); `tools/call` runs the governed pipeline with server-minted single-tool permits. A third opt-in endpoint, `POST /mcp/public` (`ENABLE_PUBLIC_MCP_ENDPOINT`, default off), is unauthenticated and read-only: its three tools verify portable receipts and mirror public discovery metadata, and nothing reachable from it mints permits, debits wallets, or enters the governed invoke path. Upstream execution is intentionally limited to one operator-configured Streamable HTTP server and one exact tool; resources, prompts, OAuth, stdio, and multi-upstream registry management are not implemented.
- Permits are reusable budget envelopes, not one-shot delegation chains; parent delegation containment is not implemented.
- Database service registrations remain metadata and are omitted from executable MCP discovery. Executable tools are local callables or the single configured upstream tool.
- Requests rejected before a valid permit and executable tool are established may terminate without a receipt.
- Replay safety is scoped to the governed gateway boundary. A missing trustworthy result after the durable remote send claim is signed as `delivery_uncertain`; an invalid or oversized confirmed response is signed as `response_rejected`. Both remain charged and are never automatically retried or refunded. Neither state proves the downstream effect. The complete outcome-by-outcome contract, including every crash window, is [docs/failure-semantics.md](docs/failure-semantics.md).
- Wallet isolation is enforced by application authorization and query scoping; PostgreSQL row-level security and a public multi-tenant isolation guarantee are not implemented.
- Upstream connections pin one validated resolved address for the session while preserving the configured HTTP Host and TLS SNI. Production operators should still enforce a network egress allowlist or proxy as defense in depth.
- Upstream responses are capped while streaming the identity-encoded wire body, including the JSON-RPC envelope, and retained decoded payloads are capped again after protocol validation.
- AWI/browser and sandbox proof surfaces are not production isolation boundaries.

Read [TRUST_MODEL.md](TRUST_MODEL.md), [SECURITY.md](SECURITY.md), [SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md), and [docs/threat-model.md](docs/threat-model.md) before a production evaluation.

## Security review path

Reviewing this repository adversarially? The fastest route from clone to verdict:

1. **Read the rules of engagement.** [docs/security-review-kit.md](docs/security-review-kit.md) says which target to attack, how to mint your own credentials instead of asking for production secrets, the five claims a finding has to break, what is already a documented limit, and what to put in a report.
2. **Run the proof.** `make prove-trust-plane` boots a local instance and asserts every core invariant end to end — one charge per accepted call, replay without a second debit, a signed denial receipt for the out-of-scope call, offline receipt verification, and a tampered receipt or audit event failing closed.
3. **Attack the invariants.** [`scripts/invariant_attacks/`](scripts/invariant_attacks/) is a stdlib-only hostile harness (only the receipt-forgery attack and the combined crash storm additionally invoke the offline SDK verifier, which needs `cryptography`): parallel double-charge, budget over-spend races, scope escape, receipt forgery, `kill -9` crash consistency, and credential misuse. [docs/invariant-attack-report.md](docs/invariant-attack-report.md) records each verdict — including the one invariant that broke, its root cause, and the fix that closed it.
4. **Aim at the documented weak points.** [SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md) and [TRUST_MODEL.md](TRUST_MODEL.md) list the accepted gaps — origin-trusted key distribution, no external audit anchoring, MCP as the only governed adapter. Attacks on the documented limits are the most useful ones.
5. **Map it to your framework.** [docs/owasp-agentic-top10-mapping.md](docs/owasp-agentic-top10-mapping.md) maps each OWASP Top 10 for Agentic Applications risk (ASI01–ASI10, 2026) to this plane's posture, the enforcing code, the proof that exercises it, and the honest gap.
6. **Black-box the live plane.** [docs/hard-run-report-2026-08-12.md](docs/hard-run-report-2026-08-12.md) is a dated credential-less adversarial run against the production deployment, with reproduction commands.

Findings: private security advisory per [SECURITY.md](SECURITY.md); [docs/security-review-kit.md](docs/security-review-kit.md#5-what-makes-a-finding-land) lists what to include.

## Tests and release gates

```bash
# Product tests; proof-surface tests excluded
make test

# Full suite, including proof surfaces
make test-all

# Whole-application coverage report
make coverage

# Focused trust modules; enforces at least 80% coverage
make trust-coverage-gate

# Offline Railway IaC package/graph contract first, then trust tests (including
# the adversarial five-claims pass), coverage, demo, and
# discovery/OpenAPI/inventory drift. CI runs this same script as the required
# `trust_release_gate` check.
make trust-release-gate

# Two-process crash-consistency proof; needs a dedicated, empty PostgreSQL
# database in DATABASE_URL. Skips unless explicitly opted in.
make prove-crash-recovery
```

`make test`, `make test-all`, and `make coverage` provision requirements through `uv`. The focused coverage and release-gate targets resolve their interpreter through a shared helper (`scripts/lib/python_env.sh`): when `uv` is available they provision the pinned requirements automatically, exactly like the test targets; without `uv` they fall back to the first of `python3.12`/`python3`/`python` that already has the requirements installed (or an explicit `PYTHON=/path/to/python` override).

The release gate's first step installs the lock-pinned Railway SDK with package lifecycle scripts disabled and evaluates `.railway/railway.ts` offline. It fails closed if package installation fails or the graph drifts from the exact API-only service contract.

[docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) maps every proof command to the invariant it asserts — and, just as importantly, to what it does not prove. Two live suites (`make trust-conformance-live`, `make adversarial-battery-live`) run the same class of invariants against a deployment you operate; both write test data, so point them at staging. A local red-team pass (`make red-team-trust-plane-check`) attacks the trust loop against a throwaway SQLite database. The otherwise stdlib-only [`scripts/invariant_attacks/`](scripts/invariant_attacks/) harness (its receipt-forgery attack and combined crash storm shell out to the offline SDK verifier, which needs `cryptography`) runs a hostile, concurrency-aware campaign against a live `make quickstart` instance — parallel double-charge, budget over-spend, scope escape, receipt forgery, crash consistency, and credential misuse — each with a HELD/BROKE/PARTIAL verdict backed by the exact request and observed response ([docs/invariant-attack-report.md](docs/invariant-attack-report.md)).

The repository is intended to run **gate-first, execute-second**: CI exposes the release gate as one dedicated check named `trust_release_gate`, and [docs/trust-release-gate-branch-protection.md](docs/trust-release-gate-branch-protection.md) specifies the exact branch-protection settings that make it (and the other required checks) block `main`. The automated batteries prove the five claims from inside; the human usability milestone is the [stranger test](docs/stranger-test.md) — a person who has never seen the repository drives the whole governed loop and verifies the same claims from the published docs alone, asking zero questions. That test does not prove customer demand. The active business milestone is the partner-owned pilot in [the 30-day customer-validation sprint](docs/30-day-customer-validation.md).

The CI workflows also run:

- The full trust release gate as a single required check (`trust_release_gate`), with the offline Railway IaC package/graph contract first, exactly as `make trust-release-gate` runs it locally.
- Python 3.11, 3.12, and 3.13 suites (the 3.13 leg is experimental and non-blocking).
- Python SDK wheel/sdist builds, clean-install smoke tests, typed-client tests, Ruff, and mypy on Python 3.10 through 3.12.
- Ruff and mypy.
- Production-like startup and routing checks.
- Migration-from-empty-database checks.
- PostgreSQL permit/refund concurrency tests plus two-process crash and replay proofs against the same row-locking backend.
- Governed upstream replay, failure accounting, dispatch reconciliation, evidence-linkage, and tenant-isolation tests.
- Trust-plane and adversarial demo smoke tests.

Static test-count and coverage badges are intentionally avoided because they become stale; the CI badge and release gates are the source of truth.

## Repository map

| Path | Role |
|---|---|
| [`app/trust/`](app/trust/) | Protocol-neutral trust facade and governed adapter boundary |
| [`app/routers/mcp.py`](app/routers/mcp.py) | Governed MCP orchestration |
| [`app/services/`](app/services/) | Permits, receipts, keys, billing, audit, idempotency, upstream MCP, and reconciliation |
| [`app/db/`](app/db/) | SQLModel schema, database lifecycle, and converters |
| [`migrations/`](migrations/) | Alembic history; use migrations for production schema changes |
| [`scripts/`](scripts/) | Reproducible demos, release gates, OpenAPI export, and operator helpers |
| [`tests/`](tests/) | Product, negative-path, concurrency, and proof-surface tests |
| [`b2a_sdk/`](b2a_sdk/) | Python trust SDK 0.5.0 source and release build |
| [`wrappers/`](wrappers/) | LangChain, CrewAI, AutoGen, and OpenAI (function calling / Agents SDK) wrapper packages driving the governed permit → invoke → receipt flow; source-only, not published to any index |
| [`awi_sdk/`](awi_sdk/) | Agentic Web Interface SDK sources (Python and TypeScript); frozen proof surface, not published |
| [`framework_integrations/`](framework_integrations/) | Source examples for agent frameworks; not published packages |
| [`site/`](site/) | Static marketing and discovery pointer site |

### Python SDK 0.5.0

HTTP and MCP are the canonical integration surfaces. CI builds and smoke-tests Python SDK 0.5.0 wheels and sdists on Python 3.10 through 3.12. A matching `python-sdk-v*` tag attaches those artifacts to a GitHub release; the package is not published to PyPI. The source version may be ahead of the latest release artifact. The typed `AgentMiddlewareClient` covers tool discovery, permit creation, governed invocation, receipt verification, and evidence retrieval, and exposes idempotency conflicts and delivery uncertainty as explicit errors. For repository development (installs from this repo, not PyPI):

```bash
python -m pip install -e './b2a_sdk[dev]'
```

`B2AClient` remains as deprecated compatibility during the 0.4.x transition. No TypeScript package is published. Do not advertise PyPI or npm installation.

Offline receipt verification is deliberately dependency-minimal: the `b2a-verify-receipt` CLI (and `verify_bundle`) verify a signed receipt against a published key set with only `cryptography` installed — no networking library and no account. Importing the package no longer pulls in the HTTP client, so `pip install "./b2a_sdk[verify]"` (or just `cryptography` with `PYTHONPATH=b2a_sdk/src`) is enough to check a receipt. The networked `--issuer` fetch is the only path that additionally needs `httpx`.

## Documentation

- [docs/README.md](docs/README.md) — start here: evaluation, integration, SDK, security, and pilot documentation paths
- [docs/30-day-customer-validation.md](docs/30-day-customer-validation.md) — active company milestone: customer interviews, partner-owned pilot, and day-30 decision gate
- [WEDGE.md](WEDGE.md) — narrow product thesis and first design-partner motion
- [ELEVATOR_PITCH.md](ELEVATOR_PITCH.md) — bounded pitch copy at four lengths, with objection handling
- [docs/PRODUCT_STRATEGY.md](docs/PRODUCT_STRATEGY.md) — strategy assessment and priorities
- [docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) — every proof command, what it proves, and what it does not
- [docs/stranger-test.md](docs/stranger-test.md) — the human milestone: a stranger drives the governed loop and checks the five claims from the public docs alone
- [docs/trust-release-gate-branch-protection.md](docs/trust-release-gate-branch-protection.md) — gate-first branch protection: the exact required checks for `main`
- [docs/hard-run-report-2026-08-12.md](docs/hard-run-report-2026-08-12.md) — adversarial black-box run against the live production trust plane, with reproduction commands
- [docs/external-surface-review-2026-08-23.md](docs/external-surface-review-2026-08-23.md) — dated black-box review of the deployed origins from outside, and the deploy gap it exposed
- [docs/reality-check-2026-09-01.md](docs/reality-check-2026-09-01.md) — dated evidence-level audit of the live deployment from raw public responses: what is verified, what the upstream `partner.echo` actually is, the rate-limit scope, and the commercial gaps ranked by decision value
- [docs/invariant-attack-report.md](docs/invariant-attack-report.md) — hostile concurrency/tampering/crash/credential campaign against a local instance, the one invariant it broke (permit-cap over-spend on SQLite), and the fix that closed it
- [docs/owasp-agentic-top10-mapping.md](docs/owasp-agentic-top10-mapping.md) — OWASP Top 10 for Agentic Applications (ASI01–ASI10, 2026) mapped to controls, proofs, and known gaps
- [docs/security-review-kit.md](docs/security-review-kit.md) — rules of engagement for an external reviewer: which target to attack, how to mint your own credentials, the claims a finding must break, and the limits already documented
- [docs/failure-semantics.md](docs/failure-semantics.md) — every terminal outcome of a metered call that dies mid-flight, and the test that proves each
- [docs/agent-accountability.md](docs/agent-accountability.md) — why an autonomous agent runs inside the permit/receipt loop, how to verify a receipt offline, and what receipts do not prove
- [DESIGN_PARTNER_GUIDE.md](DESIGN_PARTNER_GUIDE.md) — partner evaluation path
- [docs/golden-path.md](docs/golden-path.md) — wallet-scoped end-to-end API flow
- [docs/denial-details.md](docs/denial-details.md) — what a governed denial tells an agent, and what it deliberately withholds
- [docs/permit-requests.md](docs/permit-requests.md) — an agent asks a human for authority; the middleware mints the permit from the reviewed terms
- [docs/signed-quotes.md](docs/signed-quotes.md) — signed, single-use price commitments the charge honors
- [docs/human-approval-gate.md](docs/human-approval-gate.md) — pausing a governed invoke on a human decision
- [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) — replace the demo tool with one internal tool
- [docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md) — operator-gated key provisioning
- [docs/api-key-rotation.md](docs/api-key-rotation.md) — rotating bootstrap-admin env keys and wallet keys; replacement keys inherit the source key's expiry and remaining use budget and never widen authority
- [docs/static-dev-api-keys.md](docs/static-dev-api-keys.md) — static local dev/training keys and self-serve dev key provisioning
- [docs/PROOF_SURFACES.md](docs/PROOF_SURFACES.md) — frozen surface inventory
- [docs/tech-debt-remediation-plan.md](docs/tech-debt-remediation-plan.md) — agent-executable hardening plan and status
- [docs/deploy-railway.md](docs/deploy-railway.md) — supported deployment SOP
- [docs/settlement-rails.md](docs/settlement-rails.md) — rail conformance checklist (design note; settlement stays frozen)
- [docs/discovery-standards-proposal.md](docs/discovery-standards-proposal.md) — discovery honesty profile draft
- [docs/authority-required-flow.md](docs/authority-required-flow.md) — designed `tools/call` → authority-required → approval → resume contract for insufficient-authority calls (design note; not yet implemented)
- [b2a_sdk/README.md](b2a_sdk/README.md) — typed Python trust-loop client and release artifacts
- [CONTRIBUTING.md](CONTRIBUTING.md) — development and contribution guidance
- [GOVERNANCE.md](GOVERNANCE.md) — maintainership, continuity, and funding posture

## License

[MIT](LICENSE)
