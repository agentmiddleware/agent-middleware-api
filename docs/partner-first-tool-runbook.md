# Partner First-Tool Runbook

One-pager for replacing the local demo tool with one real Streamable HTTP MCP
tool.

## Goal

Prove this transaction-integrity loop for **one** partner-owned consequential
staging mutation — nothing else:

```text
permit → logical action → bounded configured consumption → one gateway dispatch
→ confirmed outcome | delivery_uncertain → linked receipt/audit → reconcile
```

Reference demo tool: `trust-plane-echo` (`make prove-trust-plane`).

## Placeholders

Fill these before the walkthrough:

| Placeholder | Example | Partner value |
|-------------|---------|---------------|
| `YOUR_TOOL_ID` | `staging.refunds.create` | |
| `UPSTREAM_TOOL_NAME` | `refund_create` | |
| `UPSTREAM_MCP_URL` | `https://mcp.partner.example/mcp` | |
| `CREDITS_PER_CALL` | `3.0` | |
| `MAX_CREDITS` | `50` | |
| `EFFECT_LOOKUP_COMMAND` | Exact partner query by invocation/idempotency ID | |
| `AMBIGUITY_ARM_COMMAND` | One-shot: commit synthetic effect, then withhold response | |
| `AMBIGUITY_RESET_COMMAND` | Disarm the staging fault and clean synthetic state | |

The example is illustrative, not customer evidence. The selected action
qualifies only when a named partner owns it, a duplicate would have a concrete
consequence, the staging effect is synthetic or redacted, and the partner
engineer can authoritatively query whether the effect was applied.

The partner-value cells for the three operational controls above must contain
exact commands or queries, expected output, and the responsible operator. A
description such as “check the database” is not enough for an independently
repeatable pilot.

## Environment

```bash
export TRUST_MODE_ENABLED=true
export ALLOW_LEGACY_UNPERMITTED_MCP=false
export ENABLE_PROOF_SURFACES=false
export TRUST_SIGNING_PRIVATE_KEY_B64=...   # from secret manager
export VALID_API_KEYS=...                  # bootstrap admin only
export DATABASE_URL=...
export MCP_UPSTREAM_ENABLED=true
export MCP_UPSTREAM_URL="UPSTREAM_MCP_URL"
export MCP_UPSTREAM_TOOL_NAME="UPSTREAM_TOOL_NAME"
export MCP_UPSTREAM_PUBLIC_TOOL_ID="YOUR_TOOL_ID"
export MCP_UPSTREAM_BEARER_TOKEN=...       # from secret manager
export MCP_UPSTREAM_CREDITS_PER_CALL="CREDITS_PER_CALL"
```

Do not put the bearer token in the URL, logs, manifests, or partner artifacts.
Do not mount AWI/media/oracle for this session.

## Rolling deployment safety

From the exact release checkout, require `alembic heads` to report one head, run
`alembic upgrade head`, and require the customer manifest and target
`alembic_version` to match that value. Do not copy a revision literal from this
runbook. Follow [`docs/deploy-railway.md`](deploy-railway.md) for
revision-specific drain and rollback rules.

## Configure the partner tool

The gateway performs `initialize` and `tools/list` during startup, selects the
exact `MCP_UPSTREAM_TOOL_NAME`, and exposes it as
`MCP_UPSTREAM_PUBLIC_TOOL_ID`. Configuration fails closed if the endpoint is
unreachable or that tool is absent. No database service registration is
required.

Keep a second tool id out of the permit (e.g. `YOUR_TOOL_ID.admin`) for the
out-of-scope denial step.

The partner tool must expose an authoritative effect identifier or lookup keyed
to the forwarded invocation/idempotency metadata. It must also provide a
partner-controlled staging fault that persists the synthetic effect first and
then closes or withholds the MCP response beyond
`MCP_UPSTREAM_CALL_TIMEOUT_SECONDS`. A delay before the effect is not the
ambiguity test.

### Operator-controlled live smoke server

Before a partner endpoint is available, deploy the repository's isolated
stateless smoke server as a separate service. It proves real TLS, bearer auth,
MCP discovery, metadata forwarding, and gateway dispatch; it is not a partner
integration and performs no persistent side effect.

```bash
export APP_MODULE=app.partner_mcp:app
export RUN_MIGRATIONS_ON_START=false
export PARTNER_MCP_BEARER_TOKEN=...       # generated secret, 32+ characters
export PARTNER_MCP_ALLOWED_HOSTS=exact-service-host.example
```

The service exposes public `GET /health` and authenticated Streamable HTTP at
`/mcp`, with one tool named `partner.echo`. Configure the gateway's
`MCP_UPSTREAM_URL`, tool names, and bearer token from this service, complete the
live checklist below, then replace it with the real partner endpoint. Never
describe the smoke server as evidence of partner adoption or remote
exactly-once side effects.

## Live checklist

1. `GET /.well-known/agent.json` and `GET /mcp/tools.json` — confirm
   `YOUR_TOOL_ID` and `requirePermit`.
2. Before invocation, record the partner effect count or state for the test
   operation.
3. Create sponsor wallet → agent wallet → agent API key.
4. Create permit:
   - `allowed_tools: ["YOUR_TOOL_ID"]`
   - `scopes: ["tool:YOUR_TOOL_ID:invoke", "billing:charge"]`
   - `max_credits: MAX_CREDITS`
   - `Idempotency-Key` on permit create
5. Governed invoke via `POST /mcp/messages` with `mcpContext.wallet_id`,
   `permit_id`, and `idempotency_key`.
6. Show ledger debit + `GET /v1/receipts/verify`; have the partner engineer
   confirm exactly one partner-side effect and record its effect ID.
7. Replay the same idempotency key → same `receipt_id`, no second gateway
   dispatch or debit, and partner effect count still one.
8. Reuse the same key with changed input → `idempotency_key_reused`, with no new
   effect.
9. Call the out-of-scope tool under the same permit → deny
   (`permit_tool_not_allowed`).
10. Call `YOUR_TOOL_ID` with no permit → deny (`permit_required`).
11. Arm the partner-controlled ambiguity fault for one fresh idempotency key.
    Require the tool to persist the effect, then lose the response.
12. Require signed `delivery_uncertain`, retained charge, and no automatic
    redispatch. Replay the exact same payload and idempotency key → same
    uncertain receipt while the partner still reports one effect.
13. The partner engineer reconciles the effect as `applied`, `not_applied`, or
    `unknown` using its authoritative system and records operator, time, effect
    ID, invocation/idempotency IDs, and remediation decision. This record
    supplements the immutable gateway receipt; it must not rewrite it, refund
    automatically, or reuse the ambiguous key.
14. Run `AMBIGUITY_RESET_COMMAND` and record that the one-shot fault is disarmed
    before any other staging action proceeds.

## Pass / fail

**Technical pass:** the partner-owned agent and staging tool complete the loop,
the partner engineer verifies the receipt and completes downstream effect
reconciliation in the partner environment, and the measured integration burden
is recorded.

**Commercial signal:** the partner says what unacceptable risk would return if
the boundary were removed and commits an owner, next action, and decision date.
A follow-up meeting or "cool demo" response alone is not validation. Apply the
full gate in
[`docs/30-day-customer-validation.md`](30-day-customer-validation.md).

**Scope guard:** keep settlement, KMS, multi-framework policy, and broad
migration frozen while the single-tool loop is untrusted. Expand only if a
named prospect documents one concrete blocker, owner, date, and smallest slice
that passes the unfreeze gate in
[`30-day-customer-validation.md`](30-day-customer-validation.md). Otherwise stop
scope expansion and point to `SECURITY_LIMITATIONS.md`.

## Talk track

- Permit = bounded configured authority (wallet, tool, credits/calls, expiry,
  signature).
- The durable action/dispatch/uncertainty state machine is the product.
- Receipt and audit data are linked gateway evidence, not proof of the
  downstream effect.
- Replay, changed-input conflict, and out-of-scope denial are transaction
  semantics, not edge cases.
- The gateway guarantees at most one gateway dispatch/debit for one accepted
  idempotency key. The remote side effect is exactly once only when the upstream
  honors the forwarded idempotency key.

## Commands

```bash
make dogfood-trust-plane        # partner.notes.write playground (real side effect)
make prove-trust-plane          # local echo proof
make agent-ops-war-room         # narrated operator timeline
make red-team-trust-plane       # adversarial deny battery
```

See also: [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md),
[`DEMO_SCRIPT.md`](../DEMO_SCRIPT.md), [`WEDGE.md`](../WEDGE.md).
