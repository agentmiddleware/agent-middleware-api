# Retry-loop alerting, spend caps, and claim-before-activation

Backlog item #8. Three parts: what shipped (first-repeat alert), what caps
exist today and where, and the pinned claim-before-activation rule.

## 1. Retry-loop alert (shipped, off by default)

**Setting:** `RETRY_LOOP_ALERT_ENABLED=false` (default),
`RETRY_LOOP_ALERT_WINDOW_SECONDS=600`.

**Event:** log line `retry_loop_first_repeat` (WARNING, logger
`app.services.idempotency`) with `wallet_id`, `endpoint`,
`request_hash_prefix`, `prior_record_id`, `record_id`, `window_seconds`.
No idempotency key and no arguments are logged.

**Definition of a repeat.** A *new* idempotency key for the same caller
(wallet), the same endpoint, and the same request hash. For governed MCP
calls the request hash covers `tool_name`, `arguments`, `wallet_id`, and
`permit_id` (`effective_request_payload`, `app/routers/mcp.py`), so it is
key-independent. Same-key retries are not repeats: they replay the stored
result and never debit twice, which is the guarantee that held in the
Wallet Of Agents test.

**Fires once per window.** On creation of a new idempotency record
(`IdempotencyService.begin_with_record`) the service reads the first two
matching records inside the window ordered by `(created_at, record_id)`. It
alerts only if the new record is the second one. Further repeats inside the
window stay silent. Once the first record ages out, the next repeat alerts
again (sliding window).

**Guarantees and limits**

- Observe-only. It never blocks, and an error inside the alert query is
  swallowed (`test_alert_failure_never_blocks_the_call`).
- Covers every call that opens an idempotency record: local governed tools,
  the upstream MCP tool, and HTTP idempotency.
- Best-effort under concurrency. The ordering is total, so normally exactly
  one record alerts. Two records committed out of `created_at` order can
  produce a missed or duplicated alert.
- Not an enforcement mechanism. To *refuse* new-key repeats on the upstream
  tool, use the existing duplicate guard (`MCP_UPSTREAM_DUPLICATE_GUARD=enforce`),
  which returns `duplicate_request_new_key` with a signed denial receipt.
  That guard is upstream-only, and in `log` mode it logs **every** repeat.
  This alert is the one-line-per-loop signal.

Tests: `tests/test_retry_loop_alert.py`.

## 2. Cap inventory: what exists today

| Cap | Scope | Field / setting | Enforced where | Local tools | Upstream MCP tool |
|---|---|---|---|---|---|
| Permit credit budget | per permit | `PermitModel.max_credits` / `spent_credits` | Guarded reserve in `PermitService.authorize_and_reserve`; `McpDispatchAttemptService.authorize_reserve_and_prepare` | yes | yes |
| **Per-tool call cap** | per permit × tool | `max_calls_per_tool` → `PermitModel.max_calls_per_tool_json`, counter `tool_call_counts_json` | `PermitService._validate_model_for_action` (`permit_max_calls_exceeded`); upstream CAS on the counter + `call_slot_reserved` (`mcp_dispatch_attempts.py`) | yes | yes (`tests/test_upstream_retry_cap_enforcement.py`) |
| **Aggregate permit value cap** | per permit | `PermitModel.aggregate_value_cap` | `PermitService` validation + guarded UPDATE (`permit_aggregate_value_cap_exceeded`), counts in-flight reservations | yes | **no**: permits carrying it are refused for upstream with `permit_constraint_unsupported_for_upstream` |
| Identical-repeat window | per permit × tool × request hash | `allow_identical_repeats`, `repeat_window_seconds`, `MCP_UPSTREAM_DUPLICATE_GUARD`, `MCP_UPSTREAM_DUPLICATE_WINDOW_SECONDS` | `authorize_reserve_and_prepare` | no | yes (`log` default, `enforce` refuses) |
| **Wallet re-plan dedup** | per wallet × tool × canonical argument hash, across all permits | `WALLET_REPLAN_GUARD`, `WALLET_DEDUP_WINDOW_SECONDS`, `REPLAN_CASEFOLD_FIELDS` | `app/services/replan_guard.py`, gate in `_execute_registered_tool_inner` (`log_only` default never blocks; `enforce` refuses `wallet_duplicate_request`) | yes | yes |
| **Wallet velocity cap** | per wallet, across all permits | `WALLET_VELOCITY_MAX_CREDITS` (integer minor units), `WALLET_VELOCITY_MAX_CALLS`, `WALLET_VELOCITY_WINDOW_SECONDS` | same gate (`wallet_velocity_exceeded` under `enforce`) | yes | yes |
| Wallet daily limit | per wallet | `WalletModel.daily_limit` / `daily_spent` | `BillingEngine` charge path; the only hard daily-spend stop | yes | yes |
| Child-wallet lifetime cap | per child wallet | wallet budget | `BillingEngine` charge path | yes | yes |
| Velocity monitor | per wallet | `VELOCITY_HOURLY_LIMIT`, `VELOCITY_DAILY_LIMIT`, thresholds | `velocity_monitor.py`: alerts, auto-freeze at the freeze threshold | yes | yes |
| Policy bundle `daily_spend_limit`, `max_cost_per_action` | per wallet policy | `PolicyBundleModel` | **Not verified as enforced.** No reader outside policy CRUD (`app/services/policies.py`) was found | — | — |

### Per-session cap: gap, not added

No per-session cap exists, and none was added. This is a deliberate choice,
not an oversight in the scope:

- The gateway has no session identity in its authority model. The only
  candidate is the MCP transport `Mcp-Session-Id`, which the client controls
  and can rotate on every request. A cap keyed on it is bypassable by
  design, and in a spend-control product it would read as a control that
  is not one.
- The control that works today is **one short-lived permit per agent
  session**: `max_credits` (session budget), `max_calls_per_tool` (session
  per-tool cap), `expires_at` (session length). All three are signed,
  enforced on both execution backends, and receipted.
- A real per-session cap needs a gateway-issued session (e.g. a session
  permit that child permits draw down) plus a schema change. That is a new
  core capability, so under `AGENTS.md` it waits for a named prospect.

### Gaps worth flagging

1. `aggregate_value_cap` is unsupported on the upstream tool, which is the
   path the wedge is about. Such permits are refused there (fail-closed),
   never silently ignored.
2. Policy-bundle spend fields look like controls but no enforcement was
   found. Either wire them into the charge path or mark them advisory in the
   API docs. Not changed here.

## 3. Claim-before-activation: reject, do not park (pinned)

**Race.** A call (claim) presents a permit id whose row is not committed
yet. Activation is the commit of the permit row: direct issuance
(`PermitService.create_permit`) or approval minting under the reserved id
(`PermitRequestService._mint`). The reserved id is not returned to callers
before the mint commits (`request_to_response` exposes `permit_id` only
once it is set), so this race takes a guessed or leaked id, or a read that
runs ahead of a commit. It is not the normal flow.

**Chosen behaviour: reject.**

- The call is denied `permit_not_found` before any reservation, debit, or
  dispatch. The permit's `spent_credits` remains 0 after activation.
- The governed idempotency record for that key is completed with the
  denial (existing contract, `docs/failure-semantics.md`). A **same-key**
  retry after activation replays `permit_not_found` and does not execute.
- A **fresh key** after activation executes exactly once.

**Why not park.** Parking would hold an open claim against a budget that
does not exist yet. It would need a second actor to dispatch later, which
duplicates the one-shot dispatch claim the wedge depends on. It would also
make a guessed permit id a way to queue work. Rejecting costs one round
trip and a new key. It cannot double-charge, because the rejected key never
reached the money path.

**Client guidance.** Use the permit only after its issuance or mint response
returns it. If you get `permit_not_found` for an id you believe is valid,
retry with a **new** idempotency key. The old key is bound to the rejection.

Test: `tests/test_claim_before_activation.py`.
