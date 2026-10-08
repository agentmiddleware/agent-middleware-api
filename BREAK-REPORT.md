# BREAK-REPORT: concurrent permit reserve, wallet debit, idempotency insert

## Summary

Probed the three shared-row write paths with adversarial tests on SQLite
(asyncio races plus injected mid-transaction interleaves) and on a local
throwaway Postgres database (real concurrent sessions against migrated
schema). Found 5 real breaks, fixed and tested all 5, 0 fixed-but-failing,
0 blocked. The core guarded-UPDATE paths (permit cap, wallet balance,
idempotency unique insert, governed daily cap) held under genuine races on
both engines; every break was at a seam around those paths.

Counts: breaks found 5, fixed and tested 5, fixed but failing 0, blocked 0.

## Finding 1 (Medium): negative amounts accepted by permit budget methods

What broke: `reserve_budget`, `release_budget`, and `authorize_and_reserve`
applied any signed Decimal through their relative `spent_credits` UPDATEs. A
negative reserve shrank `spent_credits` (minting budget from nothing), a
negative release inflated it (destroying budget the permit still owns), and a
negative `authorize_and_reserve` estimate both authorized and shrank. NaN and
infinity already fail closed in the WHERE predicates, so only negatives got
through.

How to reproduce: create a funded permit, call
`reserve_budget(permit_id, Decimal("-5"))`, re-read the row, `spent_credits`
went down by 5 with no error. Same shape for the other two methods.

Root cause: `app/services/permits.py:652` (`authorize_and_reserve` built the
guarded UPDATE from an unvalidated estimate), `app/services/permits.py:1077`
(`reserve_budget`), `app/services/permits.py:1203` (`release_budget`). No
sign check existed at the service layer.

Fix: reject `amount < 0` with `PermitError("permit_invalid_amount")` at the
top of all three methods. Zero stays allowed (harmless no-op, preserves
current behavior). No live caller passes negatives today (`tool_price`,
quote creation, and the AWI credit map all refuse or never produce them),
so this is fail-closed hardening of a billing primitive, consistent with the
existing negative guards on provisioning budgets and quoted credits.

Test results:
`tests/test_concurrent_permit_wallet_idempotency.py`: 4 new tests
(`test_reserve_budget_refuses_negative_amount`,
`test_release_budget_refuses_negative_amount`,
`test_authorize_and_reserve_refuses_negative_estimate`,
`test_zero_amounts_stay_harmless_noops`). Each negative test was run against
the unfixed code and failed (no error raised, `spent_credits` moved); all
pass with the fix. Neighbor suites pass: `test_permits.py`,
`test_permit_budget_integrity.py`, `test_permit_write_contention_surface.py`,
`test_permit_reservation_unwind.py` (47 passed).

## Finding 2 (Medium, SQLite only): abandon() deleted a concurrently completed record

What broke: `abandon()` read the idempotency record, checked it carried no
response, then deleted it. On SQLite the `SELECT ... FOR UPDATE` lock is a
silent no-op, so a `complete()` that committed a response between that read
and the delete still lost the row. The completed record, replay protection
for a charge that may already have moved money, was erased; a retry of the
same key then executed as a fresh request.

How to reproduce: `test_abandon_does_not_delete_a_completed_record` injects
a full `complete()` (response plus reference) immediately after abandon's
SELECT via the repo's `interleaving_factory` seam. Unfixed code returned
`True` and the row was gone. The same interleave on Postgres serializes on
the row lock and refuses correctly, so the test is SQLite scoped.

Root cause: `app/services/idempotency.py:862` (`session.delete(record)` acted
on a stale in-memory object with no re-check at write time).

Fix: replaced the ORM delete with a guarded
`DELETE ... WHERE record_id AND response_json IS NULL AND ledger_entry_id
IS NULL` and return whether exactly one row was deleted. A zero rowcount
(the row moved on) is a no-op returning False, which callers already treat
as "retry with in-progress semantics". Behavior is unchanged on Postgres and
on every non-racing path.

Test results: the new test failed without the fix (`abandon deleted a
record carrying a response`) and passes with it. Neighbor suites pass:
`test_idempotency.py`, `test_idempotency_completion_contention.py`,
`test_ledger_write_contention.py` (25 passed).

## Finding 3 (Low): idempotency insert leaked raw lock errors other than "database is locked"

What broke: `begin_with_record` translated a lost insert race into replay
behavior for `IntegrityError` and for `OperationalError` containing exactly
"database is locked". Any other lock-shaped driver error (notably "database
table is locked" and snapshot variants) escaped as a raw 500 even when the
winner's row was durable and replayable.

How to reproduce: `test_begin_replays_winner_on_table_locked_error` injects
`OperationalError("database table is locked")` on the first commit while a
completed winner row lands concurrently. Unfixed code raised the raw error;
fixed code returns the winner's replay.

Root cause: `app/services/idempotency.py:575` (substring match narrower than
the shared `is_retryable_write_conflict` classifier in
`app/core/resilience.py`, which also matches "locked" variants and
"snapshot").

Fix: classify with `is_retryable_write_conflict(exc)` so the insert path and
the write-conflict retry share one definition of a transient lock. Genuine
faults (I/O errors, missing tables, constraints) still propagate on first
attempt. Covered by the same neighbor suites as Finding 2.

## Races that held (no change made)

Each was run as a genuine concurrent race on SQLite and, with a standalone
single-loop script, on local Postgres (throwaway database
`fleet_brk_concurrency`, migrated to head, dropped after the run):

1. Six concurrent 3-credit `authorize_and_reserve` calls against a 10-credit
cap: total reserved never exceeded the cap, and reserved total always equaled
`spent_credits`. Holds on both engines.
2. Eight concurrent 30-credit standalone charges against balance 100:
conservation held (`balance == 100 - debited`), balance never negative, no
raw errors escaped. Holds on both engines.
3. Eight concurrent identical `begin_with_record` calls under one key:
exactly one row, one record identity, losers got `IdempotencyInProgressError`,
no raw `IntegrityError` escaped. Holds on both engines.
4. Two concurrent 60-credit governed charges against `daily_limit` 100:
exactly one succeeded on both engines (row locks serialize on Postgres;
WAL snapshot conflicts plus full-transaction retry serialize on SQLite).

## Open questions

1. The guarded wallet debit UPDATE carries no daily-limit predicate; the cap
is enforced by a read check plus engine serialization today. Every
interleave I constructed either serialized correctly or failed noisily, so
there is no live hole, but a future path that weakens the serialization
would reopen it. Suggested follow-up: add the daily predicate and a
daily-specific classification on the miss path.
2. Standalone (non-governed) charges have no write-conflict retry by design,
because their velocity increment commits separately and a restart would
double count it. A lost SQLite snapshot there surfaces as a raw
`OperationalError` instead of a classified contention reason. Availability
wart only; the fix needs velocity compensation per retry and was judged out
of scope for this pass.
3. The aggregate cap floor (`_aggregate_cap_floor_excess`) is read from
receipts and folded into the reserve predicate as a constant. A receipt that
commits between that read and the UPDATE is invisible to the predicate. The
window is one statement wide and needs a settling receipt mid-reservation;
flagging for a future look, not fixed here.
