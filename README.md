# Agent Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-v1.2.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141%2B-009688)
![License](https://img.shields.io/badge/license-MIT-blue)

> **Production beta, not production complete.** Agent Middleware API is a
> self-hostable trust plane for governed MCP tool calls. It is
> **not a full agent middleware platform**, payment network, IAM replacement, or
> compliance platform.

Authorize one agent action. Charge it once. Prove what happened.

Agent Middleware API puts a control boundary between autonomous agents and
registered local tools or one operator-configured upstream MCP tool. Agents
discover tools, authenticate with wallet-scoped keys, receive bounded permits,
invoke through an HTTP/JSON-RPC MCP gateway, consume a credit budget, and get
signed receipts plus a tamper-evident audit trail.

```text
discover -> authenticate -> authorize -> invoke -> meter -> receipt -> audit -> govern
```

The initial product wedge is deliberately narrow: **replay-safe economic
authorization for metered MCP calls**. See [WEDGE.md](WEDGE.md) for the product
thesis and [SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md) for the claims the
project does not make yet.

## What is implemented

| Trust step | Implemented behavior | Primary surface |
|---|---|---|
| Discover | Agent manifest, MCP tool manifest, agent-oriented prose, OpenAPI, dependency truth | `/.well-known/agent.json`, `/mcp/tools.json`, `/llm.txt`, `/openapi.json`, `/health/dependencies` |
| Authenticate | Bootstrap operator keys plus database-issued wallet keys; trust-core API keys are stored as hashes | `X-API-Key`, `/v1/api-keys` |
| Authorize | Ed25519-signed permits bound to issuer wallet, subject wallet/key, tools, scopes, budget, nonce, and expiry | `/v1/permits` |
| Invoke | The governed HTTP/JSON-RPC MCP subset requires a permit and idempotency key and can dispatch one configured Streamable HTTP partner tool | `/mcp/messages`, `/mcp/tools/{service_id}/invoke` |
| Meter | Decimal wallet balances, row-locked debits, limits, ledger linkage, and replay-safe charging | `/v1/billing`, `/v1/me/*` |
| Receipt | Signed post-permit success, denial, and failure receipts linked to permits, idempotency records, remote dispatch attempts, ledger entries, and audit events | `/v1/receipts`, `/v1/evidence/{receipt_id}` |
| Audit | Per-wallet signed hash chains with concurrent append protection and verification | `/v1/audit`, `/v1/audit/verify-chain` |
| Govern | Policy decisions, revocation, spend boundaries, signing-key metadata, and operator repair paths | `/v1/policies`, permit revocation, `/v1/signing-keys`, refund reconciliation |

The end-to-end governed MCP path lives in
[`app/routers/mcp.py`](app/routers/mcp.py). The protocol-facing trust facade is
[`app/trust/`](app/trust/); MCP is currently the only live governed adapter.

## Product boundary

The trust plane is the product. The broader agent features in this repository
are retained as proof surfaces and are frozen unless a specific product
decision brings one through the same permit, metering, receipt, and audit loop.

| Core trust plane | Frozen proof surfaces |
|---|---|
| Wallet-scoped API keys and tenant checks | AWI, browser, DOM, passkey, and RAG demos |
| Signed permits and revocation | Content, media, IoT, oracle, and comms demos |
| Governed MCP invocation and idempotency | Red-team, RTaaS, sandbox, telemetry, and auto-PR demos |
| Wallet metering and ledger | Simulated or partial external integrations |
| Signed receipts and evidence | Framework examples not yet shipped as packages |
| Signed wallet audit chains | Marketing/demo workloads |

Production-like deployments must set `ENABLE_PROOF_SURFACES=false`; startup
refuses a production configuration that enables them. Locally mounted proof
surfaces must not be interpreted as production integrations. The complete
inventory and unfreeze rules are in
[docs/PROOF_SURFACES.md](docs/PROOF_SURFACES.md).

## Hardening now in the tree

Recent work substantially tightened the trust and accounting boundary:

- **Atomic permit admission.** Final permit checks and budget reservation occur
  while the permit row is locked. PostgreSQL concurrency tests cover competing
  reservations and revoke-versus-invoke races.
- **Replay-safe governed execution.** A repeated idempotency key returns the
  original result and receipt without a second gateway dispatch or wallet
  debit, even across the governed MCP entrypoints; changed payloads conflict.
  Remote side effects are not claimed as exactly once unless the upstream also
  honors the forwarded key.
- **Durable remote dispatch truth.** For the configured upstream tool, one
  persisted chain links the idempotency record, permit reservation, ledger
  debit, dispatch attempt, signed receipt, and audit event. Recovery finalizes
  pre-dispatch failures or marks ambiguous post-dispatch calls
  `delivery_uncertain`; it never redispatches them.
- **Process-crash recovery proof.** An opt-in PostgreSQL harness starts two
  independent Uvicorn processes against one isolated database and kills a
  worker at durable commit boundaries. It proves one side effect/debit/receipt,
  receipt-commit recovery, and fail-closed manual review after an ambiguous
  side effect without automatic redispatch.
- **Hardened upstream boundary.** Startup performs MCP `initialize` and
  `tools/list` and registers one exact Streamable HTTP tool or fails closed.
  Production requires a public HTTPS origin; redirect following and ambient
  proxy use are disabled, while unsafe addresses, secret reflection, and
  oversized metadata or results are rejected.
- **Verifiable dispatch evidence.** Evidence checks bind a remote receipt to
  its dispatch state, response hash, wallet, permit, ledger entry,
  idempotency record, and signed audit event without exposing the bearer token
  or raw request payload.
- **Failure accounting and repair.** Local tool failures, confirmed
  pre-dispatch failures, and upstream-returned errors are refunded and
  receipted. If a required refund fails, the system writes a signed
  `failed_unrefunded` receipt and a durable, bootstrap-admin-only
  reconciliation item that can be retried exactly once. Ambiguous or rejected
  post-dispatch outcomes remain charged.
- **Settlement-gated top-ups.** Direct credit minting is disabled. Stripe
  top-ups derive credits from a verified, fully settled USD PaymentIntent;
  duplicate and stale webhook events do not mint or debit twice.
- **Safer key custody.** Current wallet and service-registry models no longer
  persist legacy plaintext owner keys. Migration 025 scrubs existing values
  but retains empty compatibility columns for one rolling release; the deploy
  gate re-scrubs and asserts them after old workers drain. Wallet API keys are
  stored as SHA-256 hashes, while the trust-signing private key is injected at
  runtime and only public signing metadata is persisted.
- **Signing-key lifecycle checks.** Reusing a key ID with different material is
  rejected, disabled keys stay disabled, and retired public metadata remains
  available for historical verification.
- **Fail-closed production startup.** Production-like environments require
  strict trust mode, a valid 32-byte Ed25519 private key, durable state,
  disabled legacy unpermitted MCP, and disabled proof surfaces. A stamped
  database behind the packaged Alembic head is rejected.
- **Concurrent audit integrity.** Per-wallet chain heads serialize concurrent
  appenders, and verification detects payload tampering, broken links, and tail
  truncation.

The corresponding negative and concurrency coverage lives in
[`tests/test_trust_negative_security.py`](tests/test_trust_negative_security.py),
[`tests/test_permit_postgres_concurrency.py`](tests/test_permit_postgres_concurrency.py),
[`tests/test_refund_reconciliation.py`](tests/test_refund_reconciliation.py),
[`tests/test_stripe_integration.py`](tests/test_stripe_integration.py),
[`tests/test_secret_persistence.py`](tests/test_secret_persistence.py), and
[`tests/test_signing_key_lifecycle.py`](tests/test_signing_key_lifecycle.py).
The remote path is covered by
[`tests/test_upstream_mcp.py`](tests/test_upstream_mcp.py),
[`tests/test_mcp_upstream_governed.py`](tests/test_mcp_upstream_governed.py),
[`tests/test_mcp_dispatch_reconciliation.py`](tests/test_mcp_dispatch_reconciliation.py),
[`tests/test_mcp_dispatch_evidence.py`](tests/test_mcp_dispatch_evidence.py), and
[`tests/test_governed_persistence.py`](tests/test_governed_persistence.py).

## Quick start: prove the trust loop

Prerequisites: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and `make`.

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
make prove-trust-plane
```

The proof uses a throwaway local SQLite database and the real FastAPI routes. It
asserts all of the following in one run:

1. Agent and MCP discovery.
2. Sponsor wallet, agent wallet, and wallet-bound key provisioning.
3. Signed permit issuance for one tool and budget.
4. Governed MCP invocation and one ledger debit.
5. Signed receipt, evidence bundle, and valid audit chain.
6. Replay returning the same receipt without a second debit or execution.
7. Out-of-scope denial without a charge.
8. Detection of tampered receipt and audit data.

To run the same proof without `uv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/demo_trust_plane.py --assert
```

The walkthrough and representative output are in [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
and [docs/demo-trust-plane-output.md](docs/demo-trust-plane-output.md).

## Run the API locally

The following keeps strict trust mode enabled while using local SQLite files.
Generate the signing seed once for a new database, save it in the ignored
`.env` file or another local secret store, and reuse it on every restart:

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

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.
Generate the local signing key once per database and reuse the same key material
with the same key ID on subsequent starts; changing material under an existing
key ID is rejected to preserve historical verification.

`VALID_API_KEYS` contains bootstrap operator credentials, not agent runtime
keys. There is no public self-serve key mint. An operator creates wallets and a
wallet-scoped agent key, then transfers that key through a secure channel. See
[docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md).

### Optional: connect one upstream MCP tool

Design-partner mode exposes one exact tool from one Streamable HTTP MCP server
through the same permit, debit, receipt, evidence, and audit path:

```bash
export MCP_UPSTREAM_ENABLED=true
export MCP_UPSTREAM_URL=https://mcp.partner.example/mcp
export MCP_UPSTREAM_TOOL_NAME=partner.write
export MCP_UPSTREAM_PUBLIC_TOOL_ID=partner.notes.write
export MCP_UPSTREAM_BEARER_TOKEN=...       # secret manager only
export MCP_UPSTREAM_CREDITS_PER_CALL=7.5
```

On startup, the gateway discovers the exact upstream tool and refuses readiness
if configuration, connectivity, or discovery validation fails. Production
requires a public HTTPS URL; plain HTTP is accepted only for an explicit
loopback URL in local or test environments. The gateway forwards the invocation
idempotency key as MCP request metadata, but remote exactly-once behavior still
depends on the upstream honoring it. Inspect `/health/dependencies` for
payload-free call, dispatch-state, uncertainty, and reconciliation-backlog
counts. See [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md)
for the live checklist and failure semantics.

## Governed MCP call shape

After an operator provisions a funded wallet and key, the normal flow is:

1. Discover the tool through `/mcp/tools.json`.
2. Create a signed permit through `POST /v1/permits` with an
   `Idempotency-Key` header.
3. Invoke the permitted tool with the wallet, permit, and invocation
   idempotency key in `mcpContext`.
4. Verify the returned receipt or fetch its evidence bundle.

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

Use [docs/golden-path.md](docs/golden-path.md) for the complete HTTP sequence
and [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) to
put one real internal tool behind the governed path.

## Core API surfaces

| Surface | Purpose | Access |
|---|---|---|
| `GET /.well-known/agent.json` | Canonical agent bootstrap and product/proof boundary | Public |
| `GET /mcp/tools.json` | Currently registered MCP tools and permit requirements | Public discovery |
| `POST /v1/api-keys` | Issue a wallet-scoped runtime key | Bootstrap admin or authorized wallet |
| `POST /v1/permits` | Issue a scoped, signed permit | Authorized issuer wallet; idempotency required |
| `POST /mcp/messages` | JSON-RPC MCP list/call transport | Authentication; permit required for governed calls |
| `GET /v1/me/permits` | Current wallet's permit view | Wallet key |
| `GET /v1/me/receipts` | Current wallet's receipt view | Wallet key |
| `GET /v1/me/audit/events` | Current wallet's audit view | Wallet key |
| `POST /v1/receipts/verify` | Verify signed receipt material | Authenticated |
| `GET /v1/evidence/{receipt_id}` | Permit, dispatch, ledger, receipt, and audit evidence bundle | Authorized wallet/admin |
| `POST /v1/audit/verify-chain` | Verify a wallet audit chain | Authorized wallet/admin |
| `GET /v1/receipts/reconciliation/refunds` | Inspect failed-refund work items | Bootstrap admin only |
| `POST /v1/billing/top-up/prepare` | Create a Stripe PaymentIntent for a sponsor wallet | Authorized sponsor wallet |
| `GET /health/dependencies` | Durable-state, upstream dispatch, reconciliation, simulation, and degradation truth | Public operator check |

The generated contract at `/openapi.json` is canonical. A checked-in copy lives
at [docs/openapi.json](docs/openapi.json) and is held in sync by CI.

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

The application refuses unsafe production combinations. It also refuses
silent in-memory fallback when durable state was configured for production.
Use `alembic upgrade head` for schema changes; production startup verifies the
schema instead of relying on `create_all`.

Apply the current migration head before mixed old/current workers take traffic.
Migration 027 serializes the legacy JSON-RPC and REST governed-MCP endpoint
identities behind one wallet/idempotency-key uniqueness boundary.

The supported API deployment path is the repository Dockerfile on Railway:
[docs/deploy-railway.md](docs/deploy-railway.md). The static agent-first site in
[`site/`](site/) is a separate marketing/discovery surface, not the API runtime.

### Billing integrity

- Credits use `Decimal` values internally and expose paired exact fields where
  API compatibility also requires floats.
- Charges, transfers, refunds, wallet provisioning, and Stripe settlement use
  database transactions and row locks where ordering matters.
- Direct top-up is deprecated and returns `410 Gone`; a client-supplied token is
  not treated as proof of payment.
- Stripe webhooks are signature checked, settlement fields are validated, and
  event identities prevent duplicate application.
- This is an internal credit and budget ledger. It is not merchant settlement,
  a dispute system, or a compliance ledger.

### Remaining limits

- Signing keys are injected from environment/secret storage; an external KMS
  integration is not implemented.
- Receipts are verifiable, but there is no external transparency log.
- Audit chains are tamper-evident, not immutable against an administrator who
  can alter both the database and its chain metadata.
- MCP is the only live governed adapter; universal multi-protocol enforcement
  is not implemented.
- The public MCP surface is an HTTP/JSON-RPC tools subset. Upstream execution is
  intentionally limited to one operator-configured Streamable HTTP server and
  one exact tool; resources, prompts, OAuth, stdio, and multi-upstream registry
  management are not implemented.
- Permits are reusable budget envelopes, not one-shot delegation chains; parent
  delegation containment is not implemented.
- Database service registrations remain metadata and are omitted from
  executable MCP discovery. Executable tools are local callables or the single
  configured upstream tool.
- Requests rejected before a valid permit and executable tool are established
  may terminate without a receipt.
- Replay safety is scoped to the governed gateway boundary. A post-dispatch
  transport failure is signed as `delivery_uncertain`; an invalid or oversized
  confirmed response is signed as `response_rejected`. Both remain charged and
  are never automatically retried or refunded.
- Wallet isolation is enforced by application authorization and query scoping;
  PostgreSQL row-level security and a public multi-tenant isolation guarantee
  are not implemented.
- Upstream URL checks do not pin DNS through the later TLS connection.
  Production operators still need a network egress allowlist or proxy.
- Upstream result limits are enforced after protocol decoding, not as a
  streaming wire-byte limit.
- AWI/browser and sandbox proof surfaces are not production isolation
  boundaries.

Read [TRUST_MODEL.md](TRUST_MODEL.md), [SECURITY.md](SECURITY.md),
[SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md), and
[docs/threat-model.md](docs/threat-model.md) before a production evaluation.

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

# Trust tests + coverage + demo + discovery/OpenAPI/inventory drift
make trust-release-gate
```

`make test`, `make test-all`, and `make coverage` provision requirements through
`uv`. The focused coverage and release-gate targets assume the requirements are
already installed in the active Python environment.

The CI workflows also run:

- Python 3.11 and 3.12 suites.
- Python SDK wheel/sdist builds, clean-install smoke tests, typed-client tests,
  Ruff, and mypy on Python 3.10 through 3.12.
- Ruff and mypy.
- Production-like startup and routing checks.
- Migration-from-empty-database checks.
- PostgreSQL permit/refund concurrency tests plus two-process crash and replay
  proofs against the same row-locking backend.
- Governed upstream replay, failure accounting, dispatch reconciliation,
  evidence-linkage, and tenant-isolation tests.
- Trust-plane and adversarial demo smoke tests.

Static test-count and coverage badges are intentionally avoided because they
become stale; the CI badge and release gates are the source of truth.

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
| [`b2a_sdk/`](b2a_sdk/) | Python trust SDK 0.4.0 source and release build |
| [`framework_integrations/`](framework_integrations/) | Source examples for agent frameworks; not published packages |
| [`site/`](site/) | Static marketing and discovery pointer site |

### Python SDK 0.4.0

HTTP and MCP are the canonical integration surfaces. CI builds and smoke-tests
Python SDK 0.4.0 wheels and sdists on Python 3.10 through 3.12. Pushing the
matching `python-sdk-v0.4.0` tag attaches those artifacts to a GitHub release;
the package is not published to PyPI. The typed `AgentMiddlewareClient` covers
tool discovery, permit creation, governed invocation, receipt verification, and
evidence retrieval, and exposes idempotency conflicts and delivery uncertainty
as explicit errors. For repository development:

```bash
python -m pip install -e './b2a_sdk[dev]'
```

`B2AClient` remains as deprecated compatibility during the 0.4.x transition.
No TypeScript package is published. Do not advertise PyPI or npm installation.

## Documentation

- [WEDGE.md](WEDGE.md) — narrow product thesis and first design-partner motion
- [DESIGN_PARTNER_GUIDE.md](DESIGN_PARTNER_GUIDE.md) — partner evaluation path
- [docs/golden-path.md](docs/golden-path.md) — wallet-scoped end-to-end API flow
- [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) — replace the demo tool with one internal tool
- [docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md) — operator-gated key provisioning
- [docs/PROOF_SURFACES.md](docs/PROOF_SURFACES.md) — frozen surface inventory
- [docs/tech-debt-remediation-plan.md](docs/tech-debt-remediation-plan.md) — agent-executable hardening plan and status
- [docs/deploy-railway.md](docs/deploy-railway.md) — supported deployment SOP
- [b2a_sdk/README.md](b2a_sdk/README.md) — typed Python trust-loop client and release artifacts
- [CONTRIBUTING.md](CONTRIBUTING.md) — development and contribution guidance

## License

[MIT](LICENSE)
