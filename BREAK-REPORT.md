# Break report: dispatch reconciliation

4 breaks found. 4 fixed and tested. 0 fixed but failing. 0 blocked.

Cleanup of governed MCP dispatch attempts trusts `updated_at` and `completed_at` with no upper bound, and it refunded a returned error before it looked at an existing receipt. Local SQLite tests only. Nothing here called a live payment or production URL.

Named checks that did not break, and are now locked by tests: a second reconcile does not refund again, a matching failed_refunded receipt is kept and refunded once, a missing attempt id is refused, and a clock 30 seconds fast is left alone.

## High: a future activity time strands an in-flight attempt

What broke. A prepared or claimed attempt whose `updated_at` is days ahead is never selected as idle. The debit, the permit reservation, and the idempotency key stay held until wall time passes that future stamp plus the idle window. A caller retry of the same key did not notice the bad stamp either.

How to reproduce. Seed a charged prepared attempt (or a claimed one) and set `updated_at` to now plus 30 days. Run `reconcile(idle_seconds=300)`. The state stays prepared or claimed, and the stamp stays 30 days ahead. Retrying the idempotency key with `wait_timeout_seconds=0` raises in progress and also leaves the future stamp.

Root cause. `app/services/mcp_dispatch_attempts.py:2191` selects active rows only when `updated_at` is older than now minus the idle window. A future value never matches. `app/services/mcp_dispatch_reconciliation.py` then returns early for an active row that is not past that cutoff. `app/services/idempotency.py` used the same stale check before it would call reconcile on a retry.

Fix. Active rows more than 300 seconds ahead of the observer clock are stamped back to now, with no state change (`clamp_future_activity_timestamps` in `app/services/mcp_dispatch_attempts.py:2104`, called from `reconcile` and `reconcile_attempt`). The same sweep does not reap them. A later sweep can, after a full idle window from that observation. A retry calls the same clamp and still does not take a live owner (`app/services/idempotency.py:395`). The clamp reads first and writes only when a row matches, so a normal reconcile does not take the SQLite writer lock out from under an in-flight charge.

Test results. Before the fix, `test_future_updated_at_does_not_strand_an_in_flight_attempt`, `test_future_updated_at_on_a_claimed_attempt_waits_out_the_idle_window`, and `test_retry_of_a_future_dated_attempt_clamps_without_finalizing` failed because the future stamp was left in place. After the fix they pass: the first sweep leaves the row active with a current stamp, and a later sweep (clock moved 660 seconds) finalizes it once. A third sweep does not move money again.

## High: a future activity time hides a finished attempt

What broke. A terminal attempt with `updated_at` days ahead was skipped by the receipt, replay, and unreleased-budget queries, and `summarize` did not count it. The refund, the receipt, and the reservation release waited on the wall clock. The backlog number stayed at zero, so an alert would not fire.

How to reproduce. Seed a charged `returned_error` attempt and set `updated_at` to now plus 30 days. `summarize(idle_seconds=300)` reports `unfinalized_terminal == 0`. `reconcile(idle_seconds=300)` repairs nothing.

Root cause. The terminal list and summary queries used the same `updated_at < now - idle` predicate as live rows. A finished attempt has no live owner, so that predicate only delayed repair.

Fix. Terminal queries also match `updated_at` later than now plus 300 seconds (`_terminal_activity_due` in `app/services/mcp_dispatch_attempts.py:281`). That covers unfinalized receipts, incomplete idempotency rows, unreleased reservations, and the two terminal counts in `summarize`. Active stale counts are unchanged, so a future in-flight row is not reported as already idle. mypy typed each comparison as `bool`, so `or_` rejected both arguments. Each comparison is cast to `ColumnElement[bool]` before `or_`. The predicate is the same two comparisons.

Test results. Before the fix, `test_future_updated_at_on_terminal_attempt_still_finalizes` failed on `unfinalized_terminal == 0`. After the fix, one reconcile writes one refund, one failed_refunded receipt, releases the reservation, and the backlog drops to zero.

## High: a future completion time is signed into the audit

What broke. Reconciliation copied `completed_at` (or `updated_at`) straight into the signed audit event. A completion time 30 days ahead became the event time. Time-bounded audit reads hide that event until the future date. The chain still verified, so the bad time was durable.

How to reproduce. Seed a stale `returned_error` attempt (so the sweep selects it) and set `completed_at` to now plus 30 days. Reconcile. The audit row for that attempt has `created_at` equal to the future completion time.

Root cause. `app/services/mcp_dispatch_reconciliation.py` passed `attempt.completed_at or attempt.updated_at` into `record_audit_event` with no upper bound. The audit duplicate check treats `created_at` as part of the signed intent, so a later writer must use the same instant.

Fix. `capped_dispatch_audit_timestamp` (`app/services/mcp_dispatch_attempts.py:260`), called at `app/services/mcp_dispatch_reconciliation.py:608`. A completion time inside the 300 second allowance is kept. Past that, the attempt `created_at` is used when it is still believable, so replicas sign the same instant. If that is also unbelievable, the observer clock is used.

Test results. Before the fix, `test_future_completed_at_is_not_the_signed_audit_time` failed because audit `created_at` was 30 days ahead. After the fix the signed time is within 300 seconds of now and `verify_audit_chain` is valid.

## High: a success receipt on a returned error was refunded, then the sweep failed

What broke. If a `returned_error` attempt already had a signed receipt whose outcome was not `failed_refunded`, cleanup refunded the debit and then raised `dispatch_receipt_outcome_conflict`. The refund was already committed. The receipt still said success, the reservation stayed held, and every later sweep failed the same row.

How to reproduce. Seed a charged `returned_error` attempt and attach a signed receipt with outcome `success` on the same idempotency record. Run `reconcile(idle_seconds=300)`. The ledger gains a refund, the attempt is in `failed_attempt_ids`, and `budget_released_at` stays empty.

Root cause. `McpDispatchReconciliationService._compensate_returned_error` called `refund_charge` before it compared the receipt outcome. `refund_charge` commits in its own transaction, so the later raise could not undo it.

Fix. The outcome check now runs first (`app/services/mcp_dispatch_reconciliation.py:447`). A receipt other than `failed_refunded` raises before any refund or reservation release. A matching `failed_refunded` receipt still refunds once and is adopted. No receipt still refunds and then writes one.

Test results. Before the fix, `test_success_receipt_on_returned_error_is_not_refunded` failed with ledger counts `(1, 1)` instead of `(1, 0)`. After the fix the debit stands, the reservation stands, and there is still one receipt. `test_reconcile_adopts_an_existing_failed_refunded_receipt` passed on the old code and still passes: one refund, one receipt, a second sweep changes nothing.

## Checks that held

`test_reconcile_twice_refunds_once`, `test_reconcile_adopts_an_existing_failed_refunded_receipt`, `test_reconcile_missing_attempt_is_refused`, and `test_small_clock_skew_does_not_reap_or_rewrite_a_fresh_attempt` passed before the production edit. They still pass. A missing attempt raises `dispatch_attempt_not_found`. A 30 second fast clock is not clamped and is not reaped.

## Commands

Old code, new tests only:

`~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_mcp_dispatch_reconciliation.py -k "future_updated_at or future_completed_at or small_clock_skew or reconcile_twice or reconcile_adopts_an_existing or success_receipt_on_returned_error or reconcile_missing_attempt or retry_of_a_future" --tb=line`

Result: 6 failed, 4 passed, 27 deselected in 1.71s. The failures were the three future in-flight or retry tests, the future terminal summary test, the future audit time test, and the success-receipt refund test.

After the fix, same command: 10 passed, 27 deselected in 1.92s.

`.venv/bin/ruff check app/services/mcp_dispatch_attempts.py app/services/mcp_dispatch_reconciliation.py app/services/idempotency.py tests/test_mcp_dispatch_reconciliation.py`

Result: All checks passed.

`~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_mcp_dispatch_reconciliation.py tests/test_late_debit_reconciliation.py tests/test_live_owner_waits.py tests/test_governed_persistence.py::test_dispatch_reconciliation_queries_active_and_unfinalized_terminal --tb=line`

Result: 50 passed in 3.48s. One run before the clamp learned to read before it writes timed out in `test_cleanup_after_inflight_debit_refunds_once`. That was the extra writer lock. It passes after the read-first change.

`~/metacode/fleet/heavy .venv/bin/pytest -q tests/test_mcp_upstream_governed.py tests/test_action_recovery.py -x --tb=line`

Result: 73 passed in 6.65s.

`.venv/bin/mypy app/services/mcp_dispatch_attempts.py tests/test_mcp_dispatch_reconciliation.py`

Result: Success, no issues in 2 source files. The earlier errors were `or_` arguments typed as `bool` at lines 289 and 290.

## Open questions

A contradictory receipt is left in `failed_attempt_ids` on every sweep. Money is not moved and the receipt is not rewritten. This report does not add an operator repair for that row.

The allowance is 300 seconds. A writer a few minutes fast is not clamped, so repair is only late by that skew. A writer further ahead than that, on a still-active row, waits the full idle window after the bad stamp is noticed. In production that window is the existing live-call lifetime, 11430 seconds, not the 300 seconds the unit tests pass in. Reaping on first sight was rejected because the owner may still be inside a live call whose clock jumped.

These tests ran on the repo SQLite file. They were not run on Postgres. No migration was added. `app/core/durable_state.py` is a different store and is not on this path.
