# Optional Jev risk guard

`JEV_RISK_GUARD` is a **PROBABILISTIC ADVISORY** check of an already allowed
MCP invocation. It asks whether the arguments appear outside the permit scope,
contain agent-directed instructions, conflict with a supplied purpose, or
understate the action's risk. It may be wrong, including on adversarial input.
It is **not part of the deterministic authorization guarantee**. It never
turns a deterministic denial into an allow, bypasses idempotency, or replaces
permit, ownership, budget, allowlist or approval checks.

## Modes and defaults

| Setting | Default | Behavior |
| --- | --- | --- |
| `JEV_RISK_GUARD` | `off` | `off`: no vendor call or new metadata. `log`: record advice without blocking. `enforce`: require human review on escalation. Invalid modes are rejected at configuration construction, like the duplicate guard. |
| `JEV_RISK_GUARD_MODEL` | `jev-1.13.0` | Pinned version against which these initial thresholds were designed. |
| `JEV_RISK_GUARD_TIMEOUT_SECONDS` | `1.5` | Total HTTP timeout via `asyncio.wait_for`; one attempt, no retries. |
| `JEV_RISK_GUARD_TIERS` | `medium,high` | Comma-separated wallet-policy risk tiers to check. |
| `TYPESAFE_API_KEY` | empty | Server-side secret; missing key makes advice unavailable. |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | Vendor origin; request endpoint is `/v1/systemone`. |

Policy tiers come from `evaluate_wallet_policy`'s evaluated constraints. With
multiple active policies, the highest declared tier is used. A missing or
unknown tier is guarded. Include `low` explicitly to apply the low-tier
understatement rules; known low-tier calls are skipped by default.

In enforce mode, an escalation under a governed permit uses the existing
human-approval service even if that permit did not originally require
approval. Pending returns retryable HTTP 202 (JSON-RPC `-32005`), rejection
produces a terminal denied receipt, and approval permits the normal checks
and execution to proceed. Missing approval configuration retains the existing
`human_approval_not_configured` denial. Calls without a governed permit have
no approval path and are denied with `jev_risk_review_required`.

The deterministic policy's `approval_gate_active` remains based solely on the
permit's signed `requires_human_approval` flag. Jev cannot satisfy or loosen a
wallet policy that would already deny the call.

## Operator opt-in and data egress

Enabling `log` or `enforce` sends **tool arguments and tool/permit descriptions
to TypeSafe, a third-party vendor**. Standard plans have **no zero data
retention** according to the supplied October 3, 2026 design/reference; verify
the vendor's current terms before opting in. Secret stripping is heuristic,
not a guarantee of removing every sensitive value. Personal data and business
content may remain. Operators must approve this egress for their workloads.

State includes the registered tool name, description, service category,
declared wallet-policy tier, permit scopes/allowlist and available constraints,
the permit's approval flag, an optional agent purpose, and sanitized arguments.
Current MCP invocations have no separate agent-purpose or natural-language
permit-description field; the available scope snapshot is sent and purpose
is absent. The evaluator supports a purpose when a caller has one.

Secret patterns are ported from the supplied `jevlib.strip_secrets`, with
additional redaction of structured credential fields. Every string is
redacted before truncation to 300 characters. Traversal is capped at 128 nodes
and depth 8; serialized state is bounded to 12,000 characters, omitting large
argument/scope snapshots when necessary. Raw arguments and API keys are never
logged by the guard; failure warnings contain only the unavailable status.

## Decision rules

All questions and thresholds live in `app/policy/jev_guard.py`. Escalate when:

- Injected instructions or outside-scope probability is at least 0.70.
- `different_action` probability, averaged over Choices with reversed option
  order, is greater than 0.60.
- Risk-understatement probability is at least 0.80 and the permit does not
  already require human approval.
- Blast-radius Score is at least 2.5 with a declared low tier.
- Both irreversible and money-moving probabilities are at least 0.80 with a
  declared low tier (`IRREVERSIBLE_MONEY_LOW_TIER_THRESHOLD`).

Nouls in the inclusive 0.30–0.70 band are recorded as uncertain; uncertainty
alone does not escalate. At 0.70 the explicit injection/scope threshold still
applies. Money, message and bulk-action signals alone do not escalate.
Thresholds are starting points, not measured accuracy guarantees. Label pilot
calls in log mode and calibrate before enabling enforcement or changing models.

## Failures, evidence and replay

Timeouts, missing credentials, HTTP errors and malformed responses return
`skipped`, with `unavailable:<reason>`. Both enabled modes **fail open to the
normal deterministic decision** when Jev is unavailable. `skipped_tier` means
the declared tier was outside the configured set; no vendor call was made.

Enabled calls add `policy_metadata["jev_risk_guard"]` to invocation audits and
the existing signed receipt field `constraints_evaluated["jev_risk_guard"]`:

- `verdict`: `pass`, `escalate`, or `skipped`.
- `status`: `ok`, `skipped_tier`, or `unavailable:<reason>`.
- `reasons`, `answers` (numeric summaries, averaged purpose probabilities,
  Choice confidence and uncertain Noul IDs).
- `model` (actual response version), `model_requested`, `input_tokens`,
  `latency_ms`, `mode`, and `advisory: true`.

A governed invocation also stores a signed `jev.risk_guard` audit checkpoint
before dispatch. With the guard enabled, upstream crash reconciliation recovers
that evidence without a new vendor call. Off mode skips these advisory lookups.

**Retries and replays:** The advisory verdict is sticky for each wallet,
idempotency endpoint and idempotency key, using a deterministic hashed audit ID.
Pending approval may release the idempotency record, but a retry reuses the
stored verdict without calling Jev or writing another advisory event. In enforce
mode, a stored escalation continues to require human approval. A concurrent
insert adopts the first persisted verdict. Terminal replays return stored
results before reaching Jev; a different idempotency key gets a new evaluation.

## Estimated cost and latency

The supplied A1 design estimates 700–1,500 input tokens, typically about 1,000,
at $0.042 per million input tokens (output free): approximately $0.00004 per
guarded call, $0.04 per 1,000 or $4 per 100,000. Estimated added latency is
0.1–0.3 seconds within the default 1.5-second timeout. These are October 3,
2026 design estimates, not measurements of this integration. Actual usage is
recorded; confirm current vendor pricing and retention terms before rollout.
