# Partner First-Tool Runbook

One-pager for replacing the local demo tool with a real internal MCP tool.

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
| `YOUR_TOOL_NAME` | `CRM Search` | |
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
```

Do not mount AWI/media/oracle for this session.

## Register the partner tool

Register exactly one local MCP tool (same pattern as `scripts/demo_trust_plane.py`):

```python
registry.register_local(
    service_id="YOUR_TOOL_ID",
    name="YOUR_TOOL_NAME",
    description="Partner internal tool behind the trust plane",
    category=ServiceCategory.AGENT_COMMS,
    func=your_handler,           # real callable
    credits_per_unit=CREDITS_PER_CALL,
    unit_name="call",
    require_permit=True,
)
```

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
6. Replay same idempotency key → same `receipt_id`, no second debit.
7. Call the out-of-scope tool under the same permit → deny (`permit_tool_not_allowed`).
8. Call `YOUR_TOOL_ID` with no permit → deny (`permit_required`).

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

## Commands

```bash
make dogfood-trust-plane        # partner.notes.write playground (real side effect)
make prove-trust-plane          # local echo proof
make agent-ops-war-room         # narrated operator timeline
make red-team-trust-plane       # adversarial deny battery
```

See also: [`DESIGN_PARTNER_GUIDE.md`](../DESIGN_PARTNER_GUIDE.md),
[`DEMO_SCRIPT.md`](../DEMO_SCRIPT.md), [`WEDGE.md`](../WEDGE.md).
