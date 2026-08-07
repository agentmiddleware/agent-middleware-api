# Partner First-Tool Runbook

One-pager for replacing the local demo tool with one real Streamable HTTP MCP
tool.

## Goal

Prove this loop for **one** partner tool — nothing else:

```text
permit → governed MCP invoke → wallet charge → signed receipt
→ audit → replay (no double charge) → out-of-scope deny
```

Reference demo tool: `trust-plane-echo` (`make prove-trust-plane`).

## Placeholders

Fill these before the walkthrough:

| Placeholder | Example | Partner value |
|-------------|---------|---------------|
| `YOUR_TOOL_ID` | `internal.crm.search` | |
| `UPSTREAM_TOOL_NAME` | `crm_search` | |
| `UPSTREAM_MCP_URL` | `https://mcp.partner.example/mcp` | |
| `CREDITS_PER_CALL` | `3.0` | |
| `MAX_CREDITS` | `50` | |

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

Apply Alembic migration `024_governed_mcp_identity` before current workers take
traffic. Its additive unique index is compatible with pre-023 workers and
serializes their physical MCP endpoint keys with the current `/mcp/invoke`
identity during a rolling deployment.

The migration stops with only an aggregate conflict count if historical rows
already reuse one wallet/key across MCP endpoint generations. Do not pick or
delete one automatically; adjudicate those operations from their receipts,
ledger entries, and audit evidence, then rerun the migration.

For an emergency code rollback, keep migration 024 in place. Old workers remain
compatible and fail closed if they collide with a canonical row. Dropping the
index after canonical rows exist reopens the duplicate debit/dispatch race.

## Configure the partner tool

The gateway performs `initialize` and `tools/list` during startup, selects the
exact `MCP_UPSTREAM_TOOL_NAME`, and exposes it as
`MCP_UPSTREAM_PUBLIC_TOOL_ID`. Configuration fails closed if the endpoint is
unreachable or that tool is absent. No database service registration is
required.

Keep a second tool id out of the permit (e.g. `YOUR_TOOL_ID.admin`) for the
out-of-scope denial step.

## Live checklist

1. `GET /.well-known/agent.json` and `GET /mcp/tools.json` — confirm `YOUR_TOOL_ID` and `requirePermit`.
2. Create sponsor wallet → agent wallet → agent API key.
3. Create permit:
   - `allowed_tools: ["YOUR_TOOL_ID"]`
   - `scopes: ["tool:YOUR_TOOL_ID:invoke", "billing:charge"]`
   - `max_credits: MAX_CREDITS`
   - `Idempotency-Key` on permit create
4. Governed invoke via `POST /mcp/messages` with `mcpContext.wallet_id`, `permit_id`, `idempotency_key`.
5. Show ledger debit + `GET /v1/receipts/verify`.
6. Replay same idempotency key → same `receipt_id`, no second gateway dispatch
   or debit.
7. Call the out-of-scope tool under the same permit → deny (`permit_tool_not_allowed`).
8. Call `YOUR_TOOL_ID` with no permit → deny (`permit_required`).
9. Force a post-dispatch timeout → signed `delivery_uncertain`, charge retained,
   and no automatic retry.

## Pass / fail

**Pass:** partner accepts the loop for this one tool and schedules a follow-up
to put a staging MCP endpoint behind the same path.

**Fail / stop:** partner asks for settlement, KMS, multi-framework policy, or
broad migration before the single-tool loop is trusted. Point to
`SECURITY_LIMITATIONS.md` and freeze proof surfaces.

## Talk track

- Permit = bounded authority (wallet, tool, budget, expiry, signature).
- MCP invoke is authorized, not only authenticated.
- Receipt is the durable proof of charge + outcome.
- Replay and out-of-scope deny are the product, not edge cases.
- The gateway guarantees one dispatch/debit for an idempotency key. The remote
  side effect is exactly once only if the partner tool honors the forwarded
  idempotency metadata.

## Commands

```bash
make dogfood-trust-plane        # partner.notes.write playground (real side effect)
make prove-trust-plane          # local echo proof
make agent-ops-war-room         # narrated operator timeline
make red-team-trust-plane       # adversarial deny battery
```

See also: [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md),
[`DEMO_SCRIPT.md`](../DEMO_SCRIPT.md), [`WEDGE.md`](../WEDGE.md).
