# Design Partner Guide

Use this guide to qualify whether one partner-owned consequential staging action
needs durable logical identity, bounded authority consumption, at-most-one
gateway dispatch/debit, explicit uncertainty, and linked evidence.

This guide proves technical fit. It does not by itself prove customer demand.
Use the interview funnel, commercial evidence gate, and partner-owned pilot
acceptance test in
[`docs/30-day-customer-validation.md`](docs/30-day-customer-validation.md).

## Best-Fit Partner

An AI platform, infrastructure, or security engineering team that:

- Operates or wants to operate an autonomous write.
- Currently prohibits or human-gates it because duplicate or ambiguous
  execution matters.
- Cannot already establish retry safety through its gateway, downstream
  idempotency, or effect lookup.
- Can provide one partner-owned, retry-sensitive staging mutation and one
  engineer.

This is best for teams that can bring that one real action to the pilot.
It is not yet a fit for teams seeking production settlement, a full IAM
replacement, or universal governance across every agent framework.

Before a paid partner uses anything beyond the constrained governed MCP path,
conduct a fresh security review of the exact deployed commit. This guide and
the public receipt are product evidence, not a security sign-off.

## Demo Path

Run the focused one-command proof first:

```bash
make demo-trust-plane
```

### API key bootstrap (gated)

There is **no public self-serve key mint**. After discovery, agents get `401`
until an operator provisions a wallet-scoped key with a bootstrap admin key.

Documented flow + script:

- [`docs/partner-api-key-bootstrap.md`](docs/partner-api-key-bootstrap.md)
- `scripts/partner_api_key_bootstrap.py`

Also advertised on `GET /.well-known/agent.json` → `authentication.bootstrap_docs`.

For local development only, dogfood a fake partner tool with a real side
effect (writes `data/dogfood_partner_notes.jsonl`):

```bash
make dogfood-trust-plane
```

Keep `ENABLE_DOGFOOD_TOOL=false` on Railway. The public evidence fixture comes
from the configured upstream `partner.echo`; it is labeled self-issued proof,
not customer traction. `partner.notes.write` must never stand in for a real
partner tool in production.

For the live engagement checklist that replaces `trust-plane-echo` / 
`partner.notes.write` with the partner's real tool id, use
[`docs/partner-first-tool-runbook.md`](docs/partner-first-tool-runbook.md).

### MCP discovery gate (Phase 2)

Live trust mode keeps both `ENABLE_PROOF_SURFACES=false` and
`ENABLE_DOGFOOD_TOOL=false`. Phase9 AWI and
marketplace-style discovery stubs are **not** part of the wedge; with Phase 2
they are gated/removed from `/mcp/tools.json` and MCP registration when proof
surfaces are off. Use one operator-configured upstream tool in production;
`partner.notes.write` remains a local test fixture only. Inventory any
dependency on Phase9 / AWI / marketplace stub tool ids and plan a swap to a
real registered tool.
Details: [`docs/tech-debt-remediation-plan.md`](docs/tech-debt-remediation-plan.md)
(Phase 2).

If the partner wants the operator narrative instead of the compact proof, run:

```bash
make agent-ops-war-room
```

If the partner is from a security team and wants to see the boundary hold
under attack rather than just on the happy path, run the adversarial battery:

```bash
make red-team-trust-plane
```

It drives one valid permit and attacks it ten ways — no permit, unknown
permit, out-of-scope tool, missing scope, over-budget, stolen permit (wrong
wallet), wrong key, expired, revoked, and tampered signature — and asserts
each is denied with a concrete reason code, that none produces a ledger debit,
and that a final valid call still charges exactly once.

Then walk the partner through the live flow:

1. Create a sponsor wallet.
2. Create an agent wallet.
3. Issue a DB-backed API key for the agent wallet.
4. Issue a signed permit for one MCP tool with wallet binding, allowed tool,
   `billing:charge`, budget, expiry, nonce, and idempotency.
5. Invoke the tool through governed MCP with `permit_id` and
   `idempotency_key`.
6. Show the wallet charge in the ledger.
7. Verify the signed receipt.
8. Verify the wallet audit chain.
9. Replay the same request and show the same receipt ID with no second debit.
10. Reuse the same key with changed input and show a fail-closed conflict.
11. Attempt a different tool under the same permit and show out-of-scope
    denial.
12. Attempt the same allowed tool with no permit at all and show the
    `permit_required` denial, proving the trust plane fails closed when
    `ALLOW_LEGACY_UNPERMITTED_MCP=false`.
13. Force response loss after the partner tool commits its staging effect.
14. Observe `delivery_uncertain`, retained configured consumption, and no
    automatic redispatch when the exact same payload and idempotency key are
    replayed.
15. Have the partner engineer reconcile the downstream effect from the
    partner's authoritative system and record its effect identifier.

## Problem Discovery Before The Demo

Start with one question:

> Which consequential action do you prohibit from full autonomy or require a
> human to operate because duplicate or uncertain execution is too risky?

Then establish the consequence, current control, and buyer before showing the
product:

- What happens when that request times out and the agent retries?
- After an ambiguous result, what establishes whether retry is safe?
- Who authorizes the action and its economic exposure today?
- Which exact approval, call allowance, or budget can be shown as consumed?
- How does the team prove what happened?
- Which existing IAM, gateway, logging, or approval control is insufficient?
- Would the team accept an inline availability, latency, and security
  dependency?
- Who owns the staging endpoint, engineering work, budget, and decision date?

Do not ask, "Would you use this?" A real signal is a partner committing its own
tool and engineer, not agreeing that the demo is interesting.

## Success Criteria

- The partner can point one consequential, retry-sensitive staging mutation
  through the MCP proxy.
- The partner can define its scoped permit and configured credit or call
  allowance.
- Exact replay does not redispatch; changed input under the same key fails
  closed.
- A partner-controlled effect-then-response-loss case produces charged
  `delivery_uncertain`, and replay creates no second gateway dispatch.
- The partner engineer reconciles the actual downstream effect from the
  partner system without rewriting the gateway receipt.
- The partner can verify the linked gateway evidence after the fact.
- The partner can see an out-of-scope request denied with an explicit reason.
- The partner's engineer can export and verify the receipt in the partner's own
  environment.
- The partner states what unacceptable risk would return if the boundary were
  removed.
- A commercial owner, next action, and decision date are recorded. Without
  those, the result is a technical pass only.

## Positioning Language

Use:

- "Make consequential agent actions transactional."
- "One logical action, bounded authority consumption, at most one gateway
  dispatch."
- "When delivery is uncertain, preserve the uncertainty and do not redispatch
  blindly."
- "Linked gateway evidence—not proof of the downstream effect."

Avoid:

- Leading with "trust plane" or "MCP gateway" as the product (category is crowded).
- "Production-ready agent payments."
- "Autonomous economic actor infrastructure."
- "Complete policy layer for all agent frameworks."
- "Compliance-grade ledger or audit storage."
- Claiming a marketing-page signature is live cryptographic proof.
- Claiming an arbitrary remote tool's side effect is exactly once when that
  tool does not honor the forwarded idempotency key.
## Do Not Promise Yet

- Settlement rails.
- Compliance-grade ledger storage.
- Full IAM replacement.
- Production sandbox isolation.
- Cross-protocol governance for every agent framework.
- Key-management hardening beyond the current trust-plane proof.
