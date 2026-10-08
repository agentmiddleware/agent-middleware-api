# Agent Middleware API

[![CI](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PetrefiedThunder/agent-middleware-api/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-v1.3.0--unreleased-lightgrey)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-BUSL--1.1%20core%20%2F%20MIT%20SDKs-blue)

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
receipt; a changed payload under the same key fails closed with an error and no
new receipt. Once a call establishes a valid permit and an executable tool,
terminal outcomes on that path — success, denial, failure, or genuine
ambiguity — are Ed25519-signed receipts you can verify offline. Requests
rejected before that point (`permit_required`, `permit_not_found`, unknown
tool) can terminate without one.

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

## Current status

`main` is the `v1.3.0` release candidate. The version is unreleased: the tag is
created only from a commit that passes the full release gate.

- **Merged:** the 2026-10-02 and 2026-10-03 QA remediation — 82 findings
  (79 fixes, 3 explicit retirements: #511, #529, #570) — plus single-action
  authority and schema 042 (`042_permit_action_binding`).
- **Locally validated, at an earlier commit:** full Python suite, fresh
  PostgreSQL, browser, and SDK checks, recorded at `079bb72`. Later merged
  commits (including the Jev runtime integration and receipt fixes) were not
  re-run as one local gate on the merged tree. Evidence:
  [docs/issue-resolution-2026-10-03/](docs/issue-resolution-2026-10-03/README.md).
- **Not verified:** hosted CI on the merged head, any staging or production
  deployment, live provider and payment behavior, and customer acceptance.
- **Single-action issuance is frozen.** `POST /v1/action-permits` is not mounted
  or advertised by the normal application, and the configured upstream has no
  qualified action binding. Permits remain reusable budget envelopes.
- **Schema 042 is a one-way boundary.** Boot refuses a database whose revision
  differs from the packaged head. Read
  [docs/schema-042-rollout.md](docs/schema-042-rollout.md) before any deploy;
  it records prerequisites, not permission to deploy.

Per-release detail: [CHANGELOG.md](CHANGELOG.md).

## See it in sixty seconds

Prerequisites: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and `make`.

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
make demo-ambiguous-retry
```

An accounts-payable agent pays invoice `INV-4417` — $250.00 to a vendor. The
payout succeeds. **The response never reaches the agent.** The agent, correctly,
retries.

The same tool runs twice, once without the boundary and once behind it:

```text
WITHOUT a transaction boundary        WITH Agent Middleware
  PAY-0001  INV-4417  $250.00           PAY-0001  INV-4417  $250.00
  PAY-0002  INV-4417  $250.00
  2 payouts, $500.00                    1 payout, $250.00
                                        1 debit · same receipt on both
                                        retry returned PAY-0001
```

The payout count is not a claim — it counts executions of the tool body. The
demo then reuses that spent key for a $9,500.00 payout (refused,
`idempotency_key_reused`, no money moved) and verifies the receipt offline
against the published key set with no credentials.

Then prove the rest of the loop asserts correctly:

```bash
make prove-trust-plane
```

That boots a local instance against a throwaway SQLite database and walks
discover, authenticate, authorize, invoke, meter, receipt, audit, govern. It
**asserts** rather than prints: the call charges once, the replay returns the
same receipt with no second debit, the audit chain verifies, the out-of-scope
call is denied, and a tampered receipt fails verification. It exits non-zero the
moment any invariant breaks.

To measure the same fault against a correct baseline instead of a naive one:

```bash
make failure-lab
```

That runs the lost-response fault against three integrations of one
simulated payment rail — no idempotency key, a correctly used native
idempotency key, and the gateway — with downstream effects counted by a
record the gateway cannot reach. It reports when the native control already
handles the fault (it does, for a client that keeps its key), what the
gateway adds and does not add, and the one failure every configuration
shares: an agent that restarts with a new key pays twice. Mechanism, report
layout, and limits: [docs/failure-lab.md](docs/failure-lab.md).

To drive the loop yourself instead of watching it:

```bash
make quickstart        # boots a real strict-trust server on 127.0.0.1:8000
```

Then follow [docs/quickstart.md](docs/quickstart.md): in about five minutes,
mint your own wallet-scoped key with no operator and no pre-shared secret,
issue yourself a permit, invoke a governed tool, deliberately try to
double-charge, and finish holding a signed receipt you verified offline.
Follow-on sections cover overspend, authority denial, and an off-the-shelf
MCP client. Every step runs in CI (`make quickstart-check`), so the
documented path cannot silently rot.

`make live-loop-proof` (against a running quickstart) writes a handoff bundle to
`data/live-loop-proof/` — portable receipts, the issuer key set, and a
`VERIFY.md` another engineer can follow with no account and no network access to
this server.

## What it guarantees

| Guarantee | What it means | Proof |
|---|---|---|
| **Charge-once under retry** | Same idempotency key → same receipt, no second dispatch, no second debit. A changed payload under that key conflicts. | `tests/test_adversarial_five_claims.py` |
| **Budget containment** | A permit's `max_credits` is reserved by one atomic guarded `UPDATE`; concurrent invocations cannot over-spend it, including on SQLite. | `tests/test_permits.py`, `postgres_permit_concurrency` CI job |
| **Interrupted-call accounting** | For the configured upstream tool, one persisted chain links the idempotency record, reservation, debit, dispatch attempt, receipt, and audit event. Ambiguity after the send claim is receipted `delivery_uncertain`, never silently redispatched. Local governed tools have no dispatch state machine and fail closed into manual review. | [docs/failure-semantics.md](docs/failure-semantics.md) |
| **Offline-verifiable receipts** | Ed25519-signed; verifiable with no credentials and no network access to the issuer, using the SDK verifier or any JOSE tooling. | `GET /v1/receipts/{id}/portable`, `/.well-known/jwks.json` |
| **Authority before money** | Out-of-scope, expired, revoked, or tampered permits are denied with a reason code *before* any charge. When a valid permit was present, that refusal is itself a signed receipt. Unpermitted and unknown-tool calls fail closed without one. | `tests/test_adversarial_five_claims.py` |

Two optional controls sit beside these guarantees and are **not** part of them:

- **Duplicate guard** (`MCP_UPSTREAM_DUPLICATE_GUARD=off|log|enforce`, default
  `log`). `enforce` denies the same arguments under a *new* idempotency key on
  the same permit and tool within the window, with `duplicate_request_new_key`.
  Detection is scoped to one `permit_id`, so it only helps flows that keep the
  original permit. On `POST /mcp`, a new key without a `permit_id` mints a fresh
  permit, so an identical retry still dispatches and debits again. It does not
  close the restart-with-a-new-key hole. See
  [docs/POLICY_ENFORCEMENT.md](docs/POLICY_ENFORCEMENT.md).
- **Jev risk advisory** (`JEV_RISK_GUARD=off|log|enforce`, default `off`). A
  probabilistic check run only after deterministic policy has allowed the call.
  It never turns a denial into an allow, can be wrong, and fails open on vendor
  errors. Redacted state leaves the gateway only after operator opt-in. See
  [docs/jev-risk-guard.md](docs/jev-risk-guard.md).

CI runs the full release gate as one required check (`trust_release_gate`), so
these claims cannot regress into `main` unproven.
[docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) maps every proof command to the
invariant it asserts — and to what it does not prove.

## What it does not do

- **Not universal exactly-once.** Gateway replay safety makes the *remote* side
  effect exactly once only if the upstream tool also honors the forwarded
  idempotency key.
- **Not proof of downstream effect.** The dispatch claim is committed *before*
  the network send, so it records the authority to send — not that a send
  happened, and never that the tool acted.
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
- **No live single-action issuance.** The code and schema 042 are merged, but
  issuance stays frozen until a binding and rollout are separately reviewed.
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

Protected routes use `X-API-Key`. On a production-like deployment there is
**no self-serve key mint**: an operator provisions a wallet-scoped key and
transfers it through a secure channel
([docs/partner-api-key-bootstrap.md](docs/partner-api-key-bootstrap.md)). The
self-provisioning the quickstart above uses is local-only — a production-like
deployment refuses to boot with it enabled
([docs/static-dev-api-keys.md](docs/static-dev-api-keys.md)).

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
| Measure the lost-response fault against a native-idempotency baseline | [docs/failure-lab.md](docs/failure-lab.md) |
| Attack it | [docs/security-review-kit.md](docs/security-review-kit.md), [docs/invariant-attack-report.md](docs/invariant-attack-report.md) |
| Check what is proven vs. claimed | [docs/PROOF_MATRIX.md](docs/PROOF_MATRIX.md) |
| See the hardening record | [docs/tech-debt-remediation-plan.md](docs/tech-debt-remediation-plan.md) (complete; a historical record, not a backlog) |
| Contribute | [CONTRIBUTING.md](CONTRIBUTING.md) |

Product site: <https://www.thisisatest.tech> · API: <https://api.thisisatest.tech>

## License

The core is source-available under the
[Business Source License 1.1](LICENSE): read it, run it, self-host it, modify
it, and redistribute it, but do not offer it to third parties as a competing
hosted service before its change date, when each version converts to MIT. The
SDKs, framework integrations, wrappers, and examples are
[MIT](b2a_sdk/LICENSE). [`LICENSING.md`](LICENSING.md) has the directory map
and the commercial-license contact.
