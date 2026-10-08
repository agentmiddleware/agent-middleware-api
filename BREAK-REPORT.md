# Break Report: MCP dispatch attempts, reconciliation, MCP routers

## Summary

Probed all seven named vectors plus adjacent router behavior with
adversarial tests against local fakes and sqlite-backed app instances.
Result: 2 real breaks found, fixed, and covered by regression tests.
0 fixed-but-failing. 0 blocked. The dispatch state machine and the
upstream transport classifier held on every probe; no change was needed
there. The pre-existing mypy pair at `mcp.py` (JEV `winner` joined with
the idempotency-record `winner`) is fixed by a separate local name.

## Findings, sorted by severity

### 1. High: legacy unpermitted MCP calls ignored the Idempotency-Key (double execution, double charge)

What broke: on `POST /mcp/messages` with legacy unpermitted calls allowed
(`ALLOW_LEGACY_UNPERMITTED_MCP=true`) and no permit, a client-supplied
`Idempotency-Key` passed validation and was then dropped. Repeating a
request with the same key and same arguments executed the tool twice and
wrote two ledger debits. Repeating with the same key and different
arguments also executed, with no conflict.

How to reproduce: register a local tool, POST `tools/call` twice with the
same `Idempotency-Key` header and identical bodies, count tool effects
and ledger rows. Before the fix: 2 effects, 2 debits. The regression
test is
`test_legacy_unpermitted_key_retry_executes_and_charges_once` in
`tests/test_mcp_legacy_unpermitted_idempotency.py`.

Root cause: `app/routers/mcp.py`, `_execute_registered_tool_inner`. The
idempotency begin/replay/complete sequence only ran when `governed_call`
was true, so the validated client key on the legacy path bound nothing.

Fix: the legacy unpermitted local-tool path now begins a record under the
transport's physical endpoint when a client key is present, replays a
stored success response, refuses a reused key with different arguments
(`idempotency_key_reused`, -32603), completes the record on success, and
abandons it on insufficient-funds denials, tool failures, and
ledger-write contention so the advised retry can run. Cross-scope key
collisions with governed rows fail closed through the normalized MCP
identity index. Upstream tools without a permit still get a clean
`permit_required` denial; that path is unchanged.

Test results: new file `tests/test_mcp_legacy_unpermitted_idempotency.py`,
13 tests, all pass. The two core tests fail with the fix disabled (2
effects and 2 debits; second call executes instead of conflicting). The
two failure-exit tests fail when only the abandon lines are neutralized
(stuck key). Related suites re-run green: idempotency key validation,
trust mode, upstream governed, dispatch reconciliation, dispatch claim,
router claim, transport hardening, standard and public endpoints,
upstream adapter, debit dispatch fence (327 tests total across the runs).

### 2. Low: dispatch origin check accepted padded values

What broke: `_assert_origin` in `app/services/mcp_dispatch_attempts.py`
accepted origins with surrounding whitespace such as
`" https://partner.example"`, while the sibling config validator
(`_parse_url_shape`) rejects them. The value is server-supplied in
practice, so reachability is limited to direct service misuse, but a
validator should refuse what the rest of the system refuses.

How to reproduce: call `_assert_origin("https://partner.example ")`;
before the fix it returned the padded value.

Root cause: `app/services/mcp_dispatch_attempts.py`, `_assert_origin`
did not check for surrounding whitespace before parsing.

Fix: reject empty values and values that differ from their stripped form
with `dispatch_upstream_origin_invalid` (2 lines). Pinned by
`test_dispatch_origin_rejects_surrounding_whitespace` and
`test_dispatch_origin_accepts_clean_shapes`, which fail and pass
respectively with the fix disabled.

Test results: included in the 13 passing tests above; fail-without-fix
confirmed by temporarily restoring the old function.

## Probed and holding (no change)

- Malformed upstream JSON on `tools/call` (HTTP 200 with garbage bytes,
  wrong result shape): classified delivery-uncertain after dispatch
  started, pre-dispatch failure on initialize. Conservative and correct;
  never refunded, never silently redispatched.
- Upstream timeout on `tools/call`: delivery-uncertain. Upstream HTTP 500
  on `tools/call`: delivery-uncertain; on initialize: pre-dispatch.
- Duplicate prepare with divergent invariants: `dispatch_idempotency_conflict`.
  Double `complete()` with divergent payload: `dispatch_terminal_conflict`;
  identical replay is idempotent. Concurrent `claim_dispatch` x8: one
  winner, seven `dispatch_claim_unavailable`.
- Reconcile after partial write: existing suites cover terminal-without-
  receipt, prepared-with-debit, and budget-release races; probes agreed.
- Tool name not in catalog (governed): -32001 with zero ledger movement,
  pinned by `test_unknown_governed_tool_charges_nothing`.
- Oversized bodies: HTTP request bodies over the limit get 413 from
  middleware; oversized terminal results raise `DispatchResultTooLargeError`;
  upstream oversized responses are rejected after dispatch.
- Malformed request envelopes: non-UTF-8, NaN/Infinity/overflow floats,
  over-nested bodies, and non-object envelopes are refused before any side
  effect (auth runs first, so unauthenticated probes correctly see 401).

## Open questions

- `_loads_dict` returns `{}` for non-dict JSON, so a corrupt
  `max_calls_per_tool_json` would silently drop a permit call cap instead
  of failing closed. Unreachable through the API (pydantic validates the
  shape at issue, and all writers use `json.dumps` on dicts); only direct
  database writes could plant such a value. Left unchanged; flagging in
  case a hardening pass wants fail-closed parsing on that control.
- Legacy refund-failure (tool failed AND the refund write failed) leaves
  the new idempotency record in progress, so retries answer -32005 until
  an operator intervenes. This is fail-closed (no second debit) and
  matches the severity the path already had (500 plus manual review), but
  it bricks the key where the governed path replays a pinned error
  receipt. Worth a follow-up only if legacy mode needs full parity.
- The `stored_jev`/`winner` mypy mismatch (JEV commit 682e158a) is
  fixed: the conflict path now binds `existing_guard` so it is not
  joined with the earlier `IdempotencyRecordModel` `winner`.
  `test_advisory_insert_race_uses_winning_escalation` asserts the
  recovered guard is a dict.

## What was not tested

- The full repository suite was not run (shared machine, many parallel
  instances); all suites touching the changed surface were run instead,
  listed above.
- Postgres-backed concurrency for the new legacy record path was not
  exercised; sqlite serialization plus the pre-existing unique index and
  the owned-record abandon protocol cover the race shape, and the
  Postgres multiprocess dispatch suites still pass unmodified.
- No live upstream MCP was touched; all upstream fault tests used local
  mock transports and fakes.
