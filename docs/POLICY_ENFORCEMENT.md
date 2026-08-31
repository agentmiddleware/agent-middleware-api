# Policy Enforcement — MCP Tool-Call Interception

**What this covers:** how the trust plane governs every MCP `tools/call` at
runtime. Enforcement is a **fail-closed, defense-in-depth pipeline**: each gate
runs in a fixed order, denies on the first failure, writes an audit event, and
— on the governed path — emits a **signed denial receipt**. Nothing is charged
and no upstream call is made unless every gate passes.

> **Where enforcement lives.** The single interception point is
> `app/routers/mcp.py::_execute_registered_tool`. It calls three independent
> evaluators (`app/policy/decisions.py`, `app/services/permits.py`,
> `app/services/policies.py`) plus the human-approval and recipient-domain
> gates. Note that `app/services/preflight.py` is a *deploy-time* GO/NO-GO
> readiness checker (keys, domains, manifests) and is **not** part of the live
> per-call path — the two are deliberately decoupled.

Last updated: 2026-08-11.

---

## 1. When a call is "governed"

Most gates below apply only on the **governed path**. A call is governed when
any of the following is true (`_execute_registered_tool`):

- a `permit_id` is supplied, **or**
- `TRUST_MODE_ENABLED` is on and `ALLOW_LEGACY_UNPERMITTED_MCP` is off (the
  shipped default), **or**
- the tool's own registration sets `require_permit` (high-value tools force the
  permit path even when legacy unpermitted MCP is otherwise allowed).

The governed path cannot be silently disabled in production. `app/core/trust_mode.py`
refuses to boot a production-like environment (`prod`, `staging`, `preview`, …)
unless **all** of these hold: `TRUST_MODE_ENABLED=true`, a valid 32-byte Ed25519
signing key is configured, `ALLOW_LEGACY_UNPERMITTED_MCP=false`, `DEBUG=false`,
`WEBAUTHN_ALLOW_MOCK=false`, and proof surfaces are off. A permissive posture is
only reachable in local/dev/test, and it logs a loud startup warning.

---

## 2. Enforcement pipeline (in order)

| # | Gate | Source | On failure |
|---|------|--------|------------|
| 1 | **Wallet ownership — unpriced** (before the idempotency store is touched) | `evaluate_tool_invocation` | `wallet_access_denied` |
| 2 | **Tool resolution + executability** | service registry | `Tool not found` / `Tool not executable` |
| 3 | **Wallet ownership — priced** (re-run with real cost, for the audit record) | `evaluate_tool_invocation` | `wallet_access_denied` |
| 4 | **Governed preconditions** | router | `permit_required` / `idempotency_key_required` |
| 5 | **Idempotency begin** (completed prior call replays its stored signed receipt) | `get_idempotency_service()` | replay short-circuit |
| 6 | **Permit validation** (Layer B) | `PermitService.validate_for_action` | `permit_*` |
| 7 | **Wallet policy bundles** (Layer C) | `evaluate_wallet_policy` | policy reason |
| 8 | **Human-approval gate** (Layer D) | `_require_human_approval` | blocks / `human_approval_unavailable` |
| 9 | **Recipient-domain binding** (Layer E) | router | `permit_recipient_domain_mismatch` |
| 10 | **Atomic budget reservation + dispatch checkpoint**, then dispatch, then meter + sign receipt | permits + dispatch services | reconcilable failure |

Ownership is checked **twice** on purpose: once unpriced *before* the
idempotency store is touched (so an unauthorized caller can neither be served
another wallet's stored receipt via the replay short-circuit nor plant an
orphaned in-progress record in the victim's `(wallet, key)` namespace), and
again with the real estimated cost to produce the priced audit record.

---

## 3. Layer A — Tenant / wallet ownership

`app/policy/decisions.py::evaluate_tool_invocation`

Binary tenant-isolation check. The call is allowed only when the caller is the
bootstrap admin **or** owns the target wallet (`auth.wallet_id == wallet_id`);
otherwise it is denied `wallet_access_denied`. This layer does not consider
cost, scope, or budget — it exists purely to stop cross-tenant access.

JWT access tokens currently support one indivisible authority profile:
`billing:charge` plus `tool:invoke`. Token exchange rejects narrower, duplicate,
or additional JWT scope sets because route-level JWT scope enforcement is not
implemented. Per-action attenuation is enforced by the signed permit in Layer B.
Refresh rotation preserves that fixed profile and consumes the parent token with
a conditional database update in the same transaction that inserts its child;
scope-less legacy refresh tokens must re-authenticate with an active API key.

---

## 4. Layer B — Permit validation

`app/services/permits.py::_evaluate` (via `validate_for_action`). Ordered,
first failure wins, every branch fails closed. The permit is an Ed25519-signed
capability bound to a wallet (and optionally an API key).

| Check | Reason code |
|-------|-------------|
| Status must be `active` | `permit_{status}` (e.g. `permit_revoked`) |
| Not past `expires_at` | `permit_expired` |
| Permit's wallet == caller wallet | `permit_wallet_mismatch` |
| Key-bound permit matches the caller's API key | `permit_key_mismatch` |
| Tool is in the permit's `allowed_tools` | `permit_tool_not_allowed` |
| Scopes include both `tool:{tool}:invoke` and `billing:charge` | `permit_scope_missing` |
| `spent_credits + estimated ≤ max_credits` | `permit_budget_exceeded` |
| Per-tool call cap `max_calls_per_tool` (v2) — malformed cap fails closed rather than coercing | `permit_max_calls_exceeded` |
| Cumulative `aggregate_value_cap` (v2): reserved-or-charged credits + estimated within cap | `permit_aggregate_value_cap_exceeded` |
| `forbidden_fields` (v2): deep scan of tool arguments for banned keys | `permit_forbidden_field:{field}` |
| Ed25519 signature over the permit verifies — checked **last** | `permit_signature_invalid` |

For upstream MCP, the per-tool call count includes the durable dispatch attempt
as soon as it is prepared. It continues to count claimed, successful,
delivery-uncertain, response-rejected, and post-dispatch error attempts; only a
durable pre-dispatch `returned_error` frees the slot. Local execution uses a
`permit_call_reservations` row keyed by the invocation's idempotency record. A
`reserved` or `consumed` row occupies the slot before a receipt exists;
`released` is allowed only while durable state still proves execution never
started. Unlinked legacy effect-bearing receipts (`success`,
`delivery_uncertain`, `response_rejected`, `failed_refunded`, and
`failed_unrefunded`) are counted separately, while receipts linked to a local
reservation or modern dispatch attempt are not counted twice. The aggregate cap
uses the permit's locked `spent_credits`, so active reservations are admitted
against the cap before any receipt exists.

---

## 5. Layer C — Wallet policy bundles

`app/services/policies.py::evaluate_wallet_policy`

Evaluates every **active** `PolicyBundle` attached to the wallet. No bundles =
allow. Within each bundle the checks run in order and the first failure wins.
All monetary comparisons are done in `Decimal` end-to-end (thresholds stored as
`Decimal`, incoming cost normalized rather than compared as float).

| Check | Reason code |
|-------|-------------|
| Bundle requires human approval | `human_approval_required` |
| Tool not in the bundle allow-list | `tool_not_allowed` |
| Service category not in the bundle allow-list | `service_category_not_allowed` |
| `estimated > max_cost_per_action` | `max_cost_per_action_exceeded` |
| `daily_spend_used + estimated > daily_spend_limit` | `daily_spend_limit_exceeded` |
| Bundle requires real effects but the call is in simulation mode | `real_effects_required` |
| `risk_tier` mismatch | *recorded on the decision, does not deny* |

Layer B (permit) and Layer C (wallet policy) are complementary: the permit is a
per-delegation capability issued to one agent for one job; policy bundles are
standing wallet-level guardrails that apply to **every** call regardless of
which permit is presented.

---

## 6. Layer D — Human approval

When the validated permit carries `requires_human_approval`, the call blocks on
the approval service before any dispatch (`_require_human_approval`; see
[`docs/human-approval-gate.md`](./human-approval-gate.md)).

If the approval service is unreachable, the call returns the **retryable**
`human_approval_unavailable` outcome rather than a terminal denial: no receipt
is written, nothing is charged, and the caller's idempotency key is released so
the identical invoke (same body, same key) can be retried once the service is
back.

---

## 7. Layer E — Recipient-domain binding

For `upstream_mcp` tools, if the permit sets `recipient_domain`, the middleware
parses the tool's registered upstream origin and requires the hostname to match
the permit's bound domain, else `permit_recipient_domain_mismatch`. This stops a
valid permit from being redirected to an unauthorized upstream destination — a
gap in naive MCP proxies that forward wherever the tool registration points.

---

## 8. Atomicity, budget reservation, and receipts

Authorization is linearized as late as possible. For a remote (`upstream_mcp`)
call, the permit budget reservation and recoverable `prepared` dispatch
checkpoint are created in the **same transaction**. For a local call, the budget
reservation and `permit_call_reservations` identity are likewise created or
adopted inside the locked permit transaction. Immediately before entering the
local callable, the row is durably changed from `reserved` to `consumed`; a
crash after that commit is treated as an ambiguous effect and never releases the
call slot or triggers automatic execution.

- Budget reservation takes a row lock (`SELECT ... FOR UPDATE`) and re-checks
  `spent_credits + amount ≤ max_credits` inside the lock, preventing concurrent
  calls from overspending a permit.
- A local reservation can move to `released` and return its budget only on a
  proven pre-execution path, with both writes committed atomically. Once
  `execution_started_at` is set, even a refunded tool error remains a consumed
  call for `max_calls_per_tool`.
- Crossing 80% / 90% / 100% of a permit's budget emits `info` / `warning` /
  `critical` billing alerts exactly once per threshold.
- On success the call is metered and a **signed receipt** is issued; on a
  governed denial a signed denial receipt is finalized so even rejections are
  provable.

---

## 9. Idempotency and replay semantics

The idempotency key identifies the **logical** invocation, not the transport
framing — JSON-RPC correlation IDs and REST-vs-JSON-RPC routing cannot produce a
second gateway dispatch for the same `(wallet_id, endpoint, key)`.

On replay of a completed call, the stored signed receipt is returned and
**mutable execution constraints are deliberately not re-evaluated** — expiry,
revocation, and remaining budget were already enforced when the receipt was
signed, and a settled outcome must not disappear if they later change. **Stable
identity constraints still apply**: wallet and key must still match. Tool scope
is intentionally not re-checked either, so that a signed *denial* for an
out-of-scope tool itself remains replayable.

---

## 10. Consolidated reason-code reference

| Reason code | Layer | Meaning |
|-------------|-------|---------|
| `wallet_access_denied` | A | Caller does not own the target wallet |
| `permit_required` | pipeline | Governed call with no permit supplied |
| `idempotency_key_required` | pipeline | Governed call with no idempotency key |
| `permit_not_found` | B | Permit ID does not resolve |
| `permit_{status}` | B | Permit not active (e.g. `permit_revoked`) |
| `permit_expired` | B | Past expiry |
| `permit_wallet_mismatch` | B | Permit bound to a different wallet |
| `permit_key_mismatch` | B | Permit bound to a different API key |
| `permit_tool_not_allowed` | B | Tool outside permit's allow-list |
| `permit_scope_missing` | B | Missing `tool:{tool}:invoke` or `billing:charge` |
| `permit_budget_exceeded` | B | Spend would exceed `max_credits` |
| `permit_max_calls_exceeded` | B | Per-tool call cap hit / malformed cap |
| `permit_aggregate_value_cap_exceeded` | B | Cumulative value cap hit |
| `permit_forbidden_field:{field}` | B | Banned argument key present |
| `permit_signature_invalid` | B | Permit signature failed verification |
| `human_approval_required` | C | Wallet policy demands approval |
| `tool_not_allowed` | C | Tool outside wallet policy allow-list |
| `service_category_not_allowed` | C | Category outside wallet policy allow-list |
| `max_cost_per_action_exceeded` | C | Per-action cost cap hit |
| `daily_spend_limit_exceeded` | C | Daily spend cap hit |
| `real_effects_required` | C | Real-effects policy vs simulation mode |
| `human_approval_unavailable` | D | Approval service unreachable (**retryable**) |
| `permit_recipient_domain_mismatch` | E | Upstream origin ≠ permit's bound domain |

---

## 11. Threat → control mapping

Summary view for security review; see [`docs/threat-model.md`](./threat-model.md)
for the full model.

| Threat | Primary control |
|--------|-----------------|
| Cross-tenant access / confused-deputy | Layer A ownership, checked before the idempotency store |
| Stolen or replayed permit | Ed25519 signature verify (B) + wallet/key binding, enforced even on replay |
| Runaway spend by an autonomous agent | Permit budget + aggregate cap (B), wallet per-action/daily caps (C), locked reservation |
| Tool/scope escalation | `allowed_tools` + explicit scope requirement (B), wallet allow-lists (C) |
| Exfiltration via argument injection | `forbidden_fields` deep-scan (B) |
| Permit redirection to a rogue upstream | Recipient-domain binding (E) |
| High-risk action without oversight | Human-approval gate (D) |
| Double-charge / duplicate side effects | Logical-invocation idempotency + atomic reserve-and-checkpoint |
| Silent loss of governance in prod | Trust-mode boot guardrails (`core/trust_mode.py`) |

---

## Source files

- `app/routers/mcp.py` — `_execute_registered_tool` (the interceptor)
- `app/policy/decisions.py` — `evaluate_tool_invocation` (Layer A)
- `app/services/permits.py` — `_evaluate` / `validate_for_action` (Layer B)
- `app/services/policies.py` — `evaluate_wallet_policy` (Layer C)
- `app/core/trust_mode.py` — production trust-posture guardrails
