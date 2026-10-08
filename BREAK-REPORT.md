# BREAK-REPORT: per-tool caps and daily limits

## Summary

Probed 7 adversarial scenarios against local test setups only (SQLite test
database, fake upstream executors, no live endpoints). Result: 1 real break
found, fixed and tested. The other 6 scenarios held: no fix needed, kept as
regression tests. No blocked scenarios. One unrelated suite showed a single
intermittent failure that passes alone and on full-file re-run (details
below, resolved as load flake).

Breaks found: 1. Fixed and tested: 1. Fixed but failing: 0. Blocked: 0.

## Finding 1 (severity: high): negative cost estimate admitted by local permit reserve

What broke: calling `PermitService.authorize_and_reserve` with a negative
`estimated_credits` returned allowed=True. The guarded UPDATE then applies
`spent_credits + estimated_credits` with no sign check, so a negative
estimate deflates `spent_credits` (budget created from nothing) while still
consuming one `max_calls_per_tool` use. The upstream reservation path already
refused negative amounts (`credits_authorized < 0`); the local path had no
equivalent guard. All current callers pass server-side non-negative amounts
(mcp router uses registered pricing, x402 validates `parsed <= 0` before
reserving, acp validates `credits <= 0` at checkout build), so this was a
missing last-line defense, not an open exploit through any current caller.

How to reproduce: create a permit (budget 100, cap 5), reserve 4 credits
(spent=4), then call `authorize_and_reserve` with `Decimal("-5")`. Before the
fix this returned allowed=True and the UPDATE row applied.

Root cause: app/services/permits.py, `_validate_model_for_action` (and
`reserve_budget`): no non-negativity check on the incoming amount before the
cap checks and the guarded UPDATE.

Fix: deny non-finite or negative estimates up front with reason
`permit_credits_invalid` in `_validate_model_for_action` (covers local
reserve, read-only validation, the upstream prepare path which calls the same
validator, and x402/acp callers), and raise `PermitError` for negative
`reserve_budget` amounts. Zero stays allowed: a zero-cost tool reserves
nothing but still holds its call slot, matching the upstream path.

Test results: new test `test_negative_estimate_denies_without_moving_budget`
in tests/test_brk_api_caps.py fails on old code (assert True is False,
allowed=True observed) and passes with the fix. Related suites all pass:
test_permits, test_permit_v2_constraints, test_local_permit_counter_contention,
test_max_calls_race, test_permit_reservation_unwind (71 passed),
test_upstream_retry_cap_enforcement, test_billing, test_velocity_monitor,
test_x402 (185 passed, 1 intermittent, see below),
test_mcp_upstream_governed, test_governed_metering (47 passed). Ruff check and
format clean on all touched files.

## Scenarios probed with no break (kept as regression tests)

1. Racing two remote reserves under max_calls=1: exactly one prepared,
   loser denied `permit_max_calls_exceeded`, counter ends at 1. The
   optimistic CAS on `tool_call_counts_json` plus refresh-and-classify holds
   under synchronized reads on SQLite.
2. Daily-limit exhaustion mid-flight: tightening `daily_limit` to 1 after a
   successful call makes the next governed call fail `insufficient_funds`,
   the tool never runs, the permit reservation (budget and call slot) is
   fully unwound, and a retry after restoring the limit succeeds.
3. Cap of 0 and negative caps in storage deny fail-closed with
   `permit_max_calls_exceeded` and move nothing. (Creation API already
   rejects these with ge=1; the probe covers tampered or legacy rows, which
   deny before the signature check.)
4. Cap overflow (2**31, 2**63, 10**30) via the creation API: accepted,
   enforced, counters count exactly. No truncation or wrap.
5. Changing caps between reserve and finalize: lowering `max_calls_per_tool`
   or `max_credits` after a reserve denies later reserves with the live
   values while the earlier reservation stands untouched; restoring the caps
   re-admits. Signature covers the cap fields, so silent tampering is still
   detected (`permit_signature_invalid` observed on direct edits).
6. Concurrent aggregate-cap reserves count in-flight: two synchronized
   reserves of 3 against a cap of 5 admit exactly one with reason
   `permit_aggregate_value_cap_exceeded` for the loser.

## Also fixed (docs)

app/routers/mcp.py `_release_local_permit_reservation` docstring claimed the
upstream path never touches the per-tool counter and capped permits are
refused that backend outright. That is stale: upstream reserves the counter
(`call_slot_reserved`) and only refuses caps in narrow reconciliation cases.
Corrected the paragraph; the operative guidance (never hand-release a remote
reservation, use `release_dispatch_budget_once`) is unchanged.

## Open questions

1. `release_budget` with a negative amount would inflate `spent_credits`
   (availability effect, not a mint). No caller does this today. Should it
   get the same guard for symmetry?
2. The HTTP charge path reports a daily-cap denial as generic
   `insufficient_funds`, indistinguishable from empty balance. Is that
   acceptable, or should the router surface a distinct daily-limit reason so
   callers know to wait rather than top up?
3. Resolved: `tests/test_acp_bridge.py::
   test_acp_rollback_release_failure_neither_masks_nor_skips_abandon` failed
   once in a combined run (`spt_stub` empty), then passed alone and passed a
   full-file re-run (24 passed). It mocks `release_budget`/`create_receipt`,
   so the permit-cap fix cannot reach it; judged a load flake on the shared
   machine, not a regression.
