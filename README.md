# Agent Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-v1.3.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-blue)

> **Agents retry. Consequential tools should not execute or charge twice.**

Agent Middleware API puts an authorization and transaction boundary in front of
MCP tools.

```text
permit → execute → receipt
```

**Same invocation again → same receipt. No second gateway dispatch. No second debit.**

A scoped, signed permit says what the agent may do and what it may spend. One
accepted idempotency key buys at most one dispatch to the configured upstream
tool and at most one wallet debit. A replay returns the original result and
receipt; a changed payload under the same key fails closed. Every outcome —
success, denial, failure, or genuine ambiguity — is an Ed25519-signed receipt
you can verify offline.

This is **not a full agent middleware platform**, a payment network, an IAM
replacement, or a compliance platform. It is a transaction control plane for
consequential agent actions, and the supported deployment is vendor-managed and
single-tenant.

## How it works

```text
                               agent
                                 │  wallet key + permit + idempotency key
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │             Agent Middleware API                │
        │                                                 │
        │   permit        tools · scope · budget · expiry │
        │   policy        allow / deny before any debit   │
        │   idempotency   one accepted key, one record    │
        │   ────────────────────────────────────────────  │
        │   dispatch fence   claimed before the send      │
        └────────────────────────┬────────────────────────┘
                                 │  at most one dispatch
                                 ▼
                         upstream MCP tool
                                 │  result, or silence
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │    receipt · evidence · wallet audit chain      │
        │    Ed25519-signed, verifiable without us        │
        └─────────────────────────────────────────────────┘
```

The dispatch fence is a gateway record, not proof that the downstream effect
occurred. When a send is claimed and no trustworthy result comes back, the call
is receipted `delivery_uncertain` and never silently redispatched. See
[docs/failure-semantics.md](docs/failure-semantics.md).

## Prove it in five minutes

Prerequisites: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and `make`.

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
make prove-trust-plane
```

One command boots a local instance against a throwaway SQLite database and
walks the whole loop — discover, authenticate, authorize, invoke, meter,
receipt, audit, govern. It **asserts** rather than prints: the call charges
once, the replay returns the same receipt with no second debit, the audit chain
verifies, the out-of-scope call is denied, and a tampered receipt fails
verification. It exits non-zero the moment any invariant breaks.

To drive the loop yourself instead of watching it:

```bash
make quickstart        # boots a real strict-trust server on 127.0.0.1:8000
```

Then follow [docs/quickstart.md](docs/quickstart.md): mint your own
wallet-scoped key with no operator and no pre-shared secret, issue yourself a
permit, invoke a governed tool, deliberately try to double-charge and overspend,
and finish holding a signed receipt you verified offline. Every step runs in CI
(`make quickstart-check`), so the documented path cannot silently rot.

`make live-loop-proof` (against a running quickstart) writes a handoff bundle to
`data/live-loop-proof/` — portable receipts, the issuer key set, and a
`VERIFY.md` another engineer can follow with no account and no network access to
this server.

## What it guarantees

| Guarantee | What it means | Proof |
|---|---|---|
| **Charge-once under retry** | Same idempotency key → same receipt, no second dispatch, no second debit. A changed payload under that key conflicts. | `tests/test_adversarial_five_claims.py` |
| **Budget containment** | A permit's `max_credits` is reserved by one atomic guarded `UPDATE`; concurrent invocations cannot over-spend it, including on SQLite. | `tests/test_permits.py`, `postgres_permit_concurrency` CI job |
| **Interrupted-call accounting** | One persisted chain links idempotency record, reservation, debit, dispatch attempt, receipt, and audit event. Ambiguity becomes a receipted state, not a silent retry. | [docs/failure-semantics.md](docs/failure-semantics.md) |
| **Offline-verifiable receipts** | Ed25519-signed; verifiable with no credentials and no network access to the issuer, using the SDK verifier or any JOSE tooling. | `GET /v1/receipts/{id}/portable`, `/.well-known/jwks.json` |
| **Authority before money** | Out-of-scope, unpermitted, expired, revoked, or tampered permits are denied with a reason code *before* any charge — and the refusal is itself a signed receipt. | `tests/test_adversarial_five_claims.py` |

CI runs the full release gate as one required check (`trust_release_gate`), so
these claims cannot regress into `main` unproven.
[docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) maps every proof command to the
invariant it asserts — and to what it does not prove.

## What it does not do

- **Not universal exactly-once.** Gateway replay safety makes the *remote* side
  effect exactly once only if the upstream tool also honors the forwarded
  idempotency key.
- **Not proof of downstream effect.** A dispatch claim records that the gateway
  sent; it never proves the tool acted.
- **Not settlement or compliance.** An internal credit ledger, not merchant
  settlement, dispute handling, or a certified compliance record.
- **Not an IAM replacement.** Wallet isolation is application-layer
  authorization and query scoping; PostgreSQL RLS and a public multi-tenant
  isolation guarantee are not implemented.
- **Not a transparency log.** Receipts verify offline, but nothing is anchored
  externally, and audit chains are tamper-evident rather than immutable against
  an administrator who controls both the database and its chain metadata.
- **One adapter, one upstream.** MCP is the only live governed adapter, and
  upstream execution is limited to one operator-configured Streamable HTTP
  server and one exact tool.
- **No delegation chains.** Permits are reusable budget envelopes; parent
  delegation containment is not implemented.
- **No public SLA**, no KMS integration, and no approval for PHI, PCI, or
  regulated production records.

The full list is [SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md); read it
with [TRUST_MODEL.md](TRUST_MODEL.md) and
[docs/threat-model.md](docs/threat-model.md) before a production evaluation.
Attacking a documented limit? Start with
[docs/security-review-kit.md](docs/security-review-kit.md), which is the rules
of engagement for an external reviewer: which target to attack, how to mint
your own credentials instead of asking for production secrets, and what turns
an observation into a finding.

## Integration

### Agent bootstrap

Autonomous clients fetch, in order:

1. `GET /.well-known/agent.json` — canonical bootstrap and product boundary
2. `GET /llms.txt` — agent-oriented prose and vocabulary
3. `GET /mcp/tools.json` — registered tools, permit requirements, exact pricing
4. `GET /openapi.json` — the canonical API contract

Before assuming real side effects, read `GET /health/dependencies` — **HTTP 200
alone does not mean every dependency is ready.** Health never replaces
authentication or permit checks.

### Governed call shape

Protected routes use `X-API-Key`. There is **no public self-serve key mint**: an
operator provisions a wallet-scoped key and transfers it through a secure
channel ([docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md)).

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

`POST /mcp/messages` is the legacy JSON-RPC transport — deprecated in the
OpenAPI contract, fully supported, and the only JSON-RPC surface in a default
local run. `POST /mcp` is the standards-compliant Streamable HTTP endpoint on
the official MCP SDK; it is opt-in today (`ENABLE_STANDARD_MCP_ENDPOINT=true`,
default off) and new integrations should prefer it. Both run the same governed
permit → meter → receipt path.

An agent holding no authority can ask a human for it with
`POST /v1/permit-requests`. Full HTTP sequence:
[docs/golden-path.md](docs/golden-path.md).

### Put your own tool behind it

```bash
export MCP_UPSTREAM_ENABLED=true
export MCP_UPSTREAM_URL=https://mcp.partner.example/mcp
export MCP_UPSTREAM_TOOL_NAME=partner.write
export MCP_UPSTREAM_PUBLIC_TOOL_ID=partner.notes.write
export MCP_UPSTREAM_BEARER_TOKEN=...       # secret manager only
export MCP_UPSTREAM_CREDITS_PER_CALL=7.5
```

On startup the gateway discovers that exact tool and refuses readiness if
configuration, connectivity, or discovery validation fails. Production requires
a public HTTPS URL. The live checklist and failure semantics are in
[docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md).

### Python SDK

The typed `AgentMiddlewareClient` covers discovery, permits, governed
invocation, receipt verification, and evidence retrieval, and surfaces
idempotency conflicts and delivery uncertainty as explicit errors. CI builds
wheels and sdists on Python 3.10–3.12 and attaches them to `python-sdk-v*`
releases. **It is not published to PyPI, and there is no TypeScript package** —
install from this repository:

```bash
python -m pip install -e './b2a_sdk[dev]'
```

Offline verification is deliberately dependency-minimal: `b2a-verify-receipt`
checks a signed receipt against a published key set with only `cryptography`
installed. See [b2a_sdk/README.md](b2a_sdk/README.md).

## Deploying it

The supported path is the repository Dockerfile on Railway, vendor-managed and
single-tenant: one project, API service, PostgreSQL database, Redis instance,
public origin, signing key, and bootstrap-admin set per customer. Deployments
must not share runtime services, databases, signing material, or operator
credentials. Production requires `TRUST_MODE_ENABLED=true`,
`ENABLE_PROOF_SURFACES=false`, and durable Postgres state; the application
refuses unsafe combinations at boot. Schema changes go through
`alembic upgrade head`.

Full SOP: [docs/deploy-railway.md](docs/deploy-railway.md).

## Repository map

| Path | Role |
|---|---|
| [`app/trust/`](app/trust/) | Protocol-neutral trust facade and governed adapter boundary |
| [`app/routers/mcp.py`](app/routers/mcp.py) | Governed MCP orchestration |
| [`app/services/`](app/services/) | Permits, receipts, keys, billing, audit, idempotency, upstream MCP |
| [`app/db/`](app/db/), [`migrations/`](migrations/) | Schema and Alembic history |
| [`tests/`](tests/), [`scripts/`](scripts/) | Product and adversarial tests; proofs and release gates |
| [`b2a_sdk/`](b2a_sdk/) | Python trust SDK (historical package name; the product is Agent Middleware) |
| [`wrappers/`](wrappers/), [`framework_integrations/`](framework_integrations/) | LangChain/CrewAI/AutoGen/OpenAI examples; source-only, unpublished |
| [`awi_sdk/`](awi_sdk/), [`site/`](site/) | Frozen proof surface; static discovery site |

Broader agent features in this repository are **frozen proof surfaces**, not
product. Production-like deployments must set `ENABLE_PROOF_SURFACES=false`;
startup refuses a production configuration that enables them. Inventory and
unfreeze rules: [docs/PROOF_SURFACES.md](docs/PROOF_SURFACES.md).

## Documentation

[docs/README.md](docs/README.md) is the documentation index. The paths that
matter most:

| You want to | Read |
|---|---|
| Decide whether this boundary fits | [WEDGE.md](WEDGE.md) |
| Run the loop yourself | [docs/quickstart.md](docs/quickstart.md) |
| Govern one real internal tool | [docs/partner-first-tool-runbook.md](docs/partner-first-tool-runbook.md) |
| Understand retry, crash, and ambiguity outcomes | [docs/failure-semantics.md](docs/failure-semantics.md) |
| Attack it | [docs/security-review-kit.md](docs/security-review-kit.md), [docs/invariant-attack-report.md](docs/invariant-attack-report.md) |
| Check what is proven vs. claimed | [docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) |
| See the hardening record | [docs/tech-debt-remediation-plan.md](docs/tech-debt-remediation-plan.md) (complete; a historical record, not a backlog) |
| Contribute | [CONTRIBUTING.md](CONTRIBUTING.md) |

Product site: <https://www.thisisatest.tech> · API: <https://api.thisisatest.tech>

## License

[MIT](LICENSE)
