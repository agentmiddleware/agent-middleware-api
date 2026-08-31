# Failure Semantics — when a metered call dies mid-flight

A governed tool call can fail before the debit, after the debit, during the
upstream dispatch, after the upstream executed, or while the result is being
committed — and a process crash can interrupt any of those. This document
defines the terminal outcome for every one of those cases: what the caller is
told, whether the wallet ends up charged, whether the tool may have executed,
and which test proves it.

Like [PROOF_MATRIX.md](PROOF_MATRIX.md), this is descriptive, not aspirational.
Every row names the code path and the test that asserts it; the last section
lists what is deliberately **not** claimed. For the claims the project never
makes, see [SECURITY_LIMITATIONS.md](../SECURITY_LIMITATIONS.md).

## The invariant

Every governed invocation with a known terminal disposition ends in **exactly
one signed terminal accounting**: an Ed25519-signed receipt (plus a
chain-hashed audit event) stating the outcome and the net charge, replayable
forever under the same idempotency key. A local post-side-effect crash with no
persisted response is the explicit exception: it remains in durable operator
review and is never redispatched automatically. Money only moves next to a
durable record that a reconciler can later compensate:

1. Budget reservation is paired with a durable execution identity in **one
   transaction**: a dispatch-attempt row for upstream MCP
   (`authorize_reserve_and_prepare`, `app/services/mcp_dispatch_attempts.py`) or
   a call-reservation row for local execution (`authorize_and_reserve`,
   `app/services/permits.py`). A failed transaction leaves neither half behind.
2. The **debit strictly precedes dispatch**, is keyed to the idempotency
   record (`operation_key`), and is linked to the attempt before the upstream
   call starts (`_charge_and_checkpoint`, `app/routers/mcp.py`).
3. A durable, one-shot **dispatch claim** (`claim_dispatch`) is committed
   immediately before the network send. A compare-and-swap moves only the
   exact unclaimed `prepared` row to `dispatch_claimed`; every later activation
   is refused, including after a lost commit acknowledgement. This claim is
   the entire basis of the refund policy below.

The dispatch attempt is a small state machine — `prepared → dispatch_claimed →
{succeeded, returned_error, delivery_uncertain, response_rejected}`, with an
independently fenced `prepared → returned_error` as the only pre-dispatch
terminal. Historical `dispatched` rows are fail-closed: they cannot be claimed
again and may only age into `delivery_uncertain`. Terminal states are absorbing,
and a claimed state is never reacquirable
(`test_dispatch_attempt_state_machine_and_bounded_result`,
`test_fresh_dispatch_claim_wins_over_pre_dispatch_reconciliation`).

## Terminal outcomes

| Outcome | Trigger | Wallet | Did the tool run? | HTTP / JSON-RPC | Proven by |
|---|---|---|---|---|---|
| `success` | Tool returned a valid result; receipt committed | **Charged** | Yes | 200 | `test_governed_mcp_invoke_returns_receipt_and_replay_does_not_double_charge`, `test_governed_upstream_success_replays_without_second_debit_or_dispatch` |
| `denied` | Permit, wallet-policy, recipient-domain, or human-approval denial — all evaluated **before money moves** | Never debited; reservation released | No | 403 / `-32003` | `test_frozen_wallet_denial_returns_receipt_and_replays_without_charge`, `test_out_of_scope_governed_mcp_denial_returns_receipt`, `test_rejected_approval_is_terminal_and_replays`, `test_upstream_permit_denials_never_charge_or_dispatch` |
| `insufficient_funds` | The charge itself was refused (balance, child-wallet cap, daily limit) | Never debited; reservation released | No | 402 / `-32004` | `test_insufficient_funds_returns_receipt_and_replays_without_charge` |
| `failed_refunded` | A **confirmed** failure: local tool raised; upstream returned `isError: true`; DNS/TLS/`initialize` failed before the dispatch claim; charge refused on the upstream path; or a crash before dispatch, finalized by the reconciler | Debit refunded (or never taken). The receipt signs `credits_charged = 0`; the ledger separately proves the correlated refund | Upstream `isError` → yes; everything else → no | 500 or 502 / `-32006` (402/403 for refused charges) | `test_governed_tool_failure_returns_refunded_receipt`, `test_confirmed_upstream_failures_refund_and_replay_without_redispatch`, `test_charge_failure_is_immediately_signed_and_releases_remote_budget`, `test_crash_between_debit_and_dispatch_reconciles_refund` |
| `delivery_uncertain` | The one-shot dispatch claim was committed, then a timeout, transport failure, or process death left the outcome unknowable | **Stays charged.** Never redispatched | **Unknown** — that is the definition | 504 / `-32005` | `test_ambiguous_or_rejected_upstream_response_stays_charged_and_replays`, `test_kill_between_dispatch_and_response_becomes_delivery_uncertain`, `test_stale_dispatched_becomes_charged_delivery_uncertain_without_retry`, `test_kill_after_remote_effect_never_redispatches_the_effect` |
| `response_rejected` | The upstream **did** respond, but the response is unusable: invalid shape, reflected bearer token, non-serializable, or over the byte cap (wire-level or at persistence) | **Stays charged** | Yes — confirmed executed | 502 / `-32006` | `test_confirmed_result_rejected_by_persistence_is_terminal_and_replayable`, `test_terminal_response_rejected_retains_charge_and_is_replayable` |
| `failed_unrefunded` | A refund was owed and the refund **itself** failed | Charged; a durable operator work item is created atomically with the receipt | Depends on the underlying failure | 500 / `-32603` | `test_governed_refund_failure_keeps_permit_budget_reserved`, `test_refund_reconciliation_retries_exactly_once_and_preserves_agent_replay` |

Requests rejected before a valid permit and an executable tool are established
(unknown tool, `permit_required`, `permit_not_found`) terminate with a signed
terminal *idempotency record* but no receipt — there is no authority to bill
against. The README states this limit; the replay still returns the original
envelope.

## Why `delivery_uncertain` cannot be "fixed"

The durable dispatch claim is written immediately before the network
send (`before_dispatch` in `app/services/upstream_mcp.py`). Every failure
**before** that claim is provably non-delivered, so it is safe to refund
and sign `failed_refunded`. Every failure **after** it is inherently
ambiguous: the upstream may or may not have executed, and no amount of gateway
logic can find out. The design response is to *preserve the ambiguity
honestly* rather than guess:

- the debit is retained and the receipt says so;
- the server **never redispatches** — the HTTP transport is built with
  `retries=0`, the adapter invokes the tool exactly once, the durable claim
  rejects every second activation, terminal states are absorbing, and the
  reconciler imports no executor at all
  (`test_governed_upstream_conflicting_payload_reuse_never_redispatches`,
  `test_losing_dispatch_claim_does_not_compensate_and_never_redispatches`);
- resolution belongs to the caller and the upstream provider, using the
  forwarded idempotency metadata (below) and the signed evidence.

Retaining the charge is a deliberate incentive choice: an ambiguous call that
auto-refunded would pay callers to induce timeouts against providers whose
side effects completed.

## Crash windows

A worker process can die at any point in the sequence. The reconciler
(`app/services/mcp_dispatch_reconciliation.py`) finalizes what the crash left
behind — "without ever redispatching", per its own docstring. Faults are
injected at each durable boundary in the tests named below.

| Window — process dies… | Detected by | Resolution | Money |
|---|---|---|---|
| **A0. after human approval, before remote preparation** (approval remains `approved`) | Effect-free idempotency sweep deletes the stale unstarted identity; the approval itself needs no repair | Retry the same key after cleanup; approval consumption, permit reservation, and `prepared` then commit atomically | Nothing moved |
| **A. after debit, before dispatch** (attempt `prepared`) | Stale-active sweep; the debit is found by its `operation_key` even if the crash preceded `attach_charge` | `failed_refunded` (`reconciled_stale_prepared`), signed receipt + audit, replay returns 502 | **Refunded**, budget released |
| **B1. after the dispatch claim, before the network send** (attempt `dispatch_claimed`) | Stale-active sweep, only after the claim independently becomes idle | `delivery_uncertain`; even when a test observer knows no request left, a restarted gateway cannot safely prove that fact and never redispatches | **Stays charged** |
| **B2. after the remote response, before terminal commit** (attempt still `dispatch_claimed`; historical rows may say `dispatched`) | Stale-active sweep | `delivery_uncertain`, signed receipt + audit, replay returns 504; the partner's known effect is not repeated | **Stays charged** |
| **C. after terminal commit, before the receipt commit** (attempt terminal, no receipt) | Terminal-without-receipt sweep; the stored canonical result is **re-hashed byte-exact** before reuse (`dispatch_stored_result_hash_mismatch` on any tamper) | The recorded terminal state is adopted and signed; a recorded `returned_error` completes its refund | Per the recorded state |
| **D1. lost COMMIT ack on reserve+prepare** | Recovery re-read adopts only an invariant-identical `prepared` row | Same attempt id returned; no second reservation | Unchanged (`test_remote_prepare_recovers_lost_commit_ack_without_double_reserving`) |
| **D2. lost COMMIT ack on the dispatch claim** | Only the still-live caller whose ephemeral secret hashes to the stored claim may adopt it | That caller may send once; every later caller is refused | Stays charged if the claim later becomes ambiguous (`test_dispatch_claim_recovers_lost_commit_ack_but_cannot_be_reacquired`) |
| **D3. lost ack on the final completion** (receipt exists, idempotency record empty) | Receipt-present / response-`NULL` sweep, which runs **before** the generic sweep | The replay record is rebuilt from the signed receipt; an existing `failed_refunded` receipt **blocks** a second budget release | Unchanged |
| **E. before any effect** (no attempt, no debit, no receipt) | Effect-free idempotency sweep | The record is deleted so the same key can genuinely retry | Nothing ever moved |

Proven by `tests/test_mcp_dispatch_reconciliation.py` (each window has a named
test — `test_crash_between_debit_and_dispatch_reconciles_refund`,
`test_kill_between_dispatch_and_response_becomes_delivery_uncertain`,
`test_terminal_success_is_reconstructed_from_bounded_result`,
`test_existing_receipt_missing_idempotency_completion_replays_full_result`,
`test_effect_free_stale_mcp_identity_is_released_for_safe_retry`) and by the
multi-process kill tests in `tests/test_mcp_postgres_multiprocess.py`.
The latter uses an independent FastMCP process to prove A0 both before and
inside atomic preparation, plus B1 and B2 across a real network boundary
(`test_remote_approval_crash_before_prepare_retries_without_losing_authority`,
`test_remote_approval_prepare_transaction_rolls_back_on_process_kill`,
`test_remote_claim_commit_before_send_crash_never_redispatches`,
`test_remote_ack_before_terminal_commit_crash_becomes_uncertain_without_redispatch`).
The same suite kills real workers immediately after debit, on either side of a
remote effect, and verifies the resulting refund or charged uncertainty
(`test_kill_between_debit_and_dispatch_refunds_without_dispatching`,
`test_kill_after_dispatch_checkpoint_is_charged_delivery_uncertain`,
`test_kill_after_remote_effect_never_redispatches_the_effect`).

The stale window is derived from the configured connection and tool-call
timeouts plus a bounded teardown margin, with a 300-second floor. A valid
long-running call therefore cannot be declared stale before its configured
execution deadline.

Reconciliation itself is idempotent by construction: audit event ids are
derived deterministically from the attempt id, refunds are keyed
`refund-{ledger_entry_id}`, budget release is exactly-once, and receipts are
unique per idempotency record — so two reconcilers racing produce one receipt
and one audit event
(`test_concurrent_dispatch_reconcilers_create_one_signed_audit_in_postgres`),
and a repeated sweep repairs zero rows. Crash-recovered receipts sign the
same permit-constraint snapshot bytes a live receipt would
(`test_reconciler_constraints_snapshot_matches_live_path`).

## The replay contract

Replaying the same idempotency key never re-executes and never re-charges; it
returns the original envelope, including the original receipt. Replay access
re-validates the permit↔wallet↔key binding first, so a revoked permit or a
different key cannot read the stored receipt.

| Stored terminal state | Replay returns |
|---|---|
| `success` | 200 with the stored result and the same `receipt_id` |
| `denied` | 403 / `-32003`, original reason and receipt |
| `insufficient_funds` | 402 / `-32004` |
| `failed_refunded` | 500/502 with the upstream error detail where recorded |
| `delivery_uncertain` | 504 / `-32005`, with the dispatch attempt reference |
| `response_rejected` | 502 / `-32006` |
| `failed_unrefunded` | 500 with the reconciliation status — a stored claim of `resolved` is **re-validated against the ledger on every replay** and rejected if unsubstantiated |

Two non-terminal answers matter to clients:

- **`idempotency_in_progress`** — another request holds this key with no
  terminal result yet. Upstream calls wait a bounded window for the winner;
  local calls answer immediately. Retry the **same** key; do not mint a new
  one, because the original may already have had a side effect.
- **`idempotency_key_reused`** — the same key arrived with a *different*
  logical payload. Fail-closed; nothing is dispatched or charged
  (`test_governed_upstream_conflicting_payload_reuse_never_redispatches`).

The idempotency identity is the *logical* call — transport-independent, so a
JSON-RPC call and its REST retry share one identity
(`test_governed_upstream_replays_across_jsonrpc_and_rest_transport`).

## Exactly-once refunds

`failed_refunded` means the correlated refund is already durable — the receipt
signs a net charge of zero, and the evidence layer independently requires the
refund ledger row to exist. When the refund itself fails, the system does not
pretend: it signs `failed_unrefunded` **atomically with** a durable
reconciliation work item, and an operator (bootstrap-admin only) retries it
later. That retry is exactly-once under concurrency: the refund entry id is
the deterministic `refund-{ledger_entry_id}`, so even a refund whose commit
ack was lost is recognized rather than duplicated
(`test_lost_refund_ack_releases_budget_without_double_refund`,
`test_concurrent_refund_reconciliation_is_exactly_once_in_postgres`). A forged
`resolved` claim without the matching ledger row fails closed on every read
and replay (`test_forged_resolved_reconciliation_without_refund_fails_closed`).

## What this deliberately does not claim

1. **Post-dispatch ambiguity is never resolved automatically.** No retry, no
   probabilistic refund. The charge stands, the receipt says
   `delivery_uncertain`, and reconciliation with the upstream is the caller's
   and operator's job.
2. **Remote exactly-once is not claimed.** The gateway forwards
   `io.agentmiddleware/invocation_id` and `io.agentmiddleware/idempotency_key`
   in the MCP call metadata; a remote side effect is exactly-once only if the
   upstream honors them.
3. **Crashed reservations on still-live permits are not reclaimed early.** A
   long-running call and a crashed one are indistinguishable from outside, so
   the reservation is conservatively held until the permit expires.
4. **A local tool's post-side-effect crash goes to operator review, not
   recovery.** With no persisted response there is nothing safe to
   reconstruct; its consumed call reservation stays counted, the idempotency
   row is counted for review, and replay stays in-progress
   (`test_post_side_effect_crash_requires_review_without_redispatch`).
5. **There is a blind window after a crash.** The reconciler runs periodically
   and sweeps rows older than the timeout-derived `idle_seconds` window (300
   seconds with the default timeout settings), in bounded batches; backlog is
   surfaced in `/health/dependencies` and the operator dispatch summary rather
   than hidden.
6. **Crash proofs are boundary-instrumented.** Faults are injected at the
   durable commit points listed above — not at arbitrary instructions, not
   database failover, not multi-node HA (see PROOF_MATRIX).
7. **Cross-process correctness is PostgreSQL's row locks.** The SQLite test
   path adds a process-local lock for determinism; it is not the
   correctness boundary.
8. **Atomic approval preparation is scoped to remote MCP dispatch.** Local tools
   retain immediate approval consumption because they have no durable dispatch
   attempt with which to share a transaction. Approval-gated consequential
   pilots must use upstream MCP; local approval-gated execution does not claim
   crash-safe authorization recovery.

## Verify it yourself

```bash
# The failure-path suites named throughout this document:
uv run --with-requirements requirements.txt python -m pytest -q \
  tests/test_mcp_trust.py \
  tests/test_mcp_upstream_governed.py \
  tests/test_mcp_dispatch_reconciliation.py \
  tests/test_refund_reconciliation.py \
  tests/test_mcp_dispatch_evidence.py \
  tests/test_governed_persistence.py

# Multi-process kill tests (PostgreSQL required):
# tests/test_mcp_postgres_multiprocess.py — see PROOF_MATRIX.md

# The whole trust-plane gate, including all of the above:
make trust-coverage-gate
```
