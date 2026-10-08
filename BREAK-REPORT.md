# Break Report: rate limit middleware and window counters

## Summary

Probed the rate limiter in `app/core/rate_limiter.py` with local adversarial
tests only (in-memory backend and a fake Redis, no live endpoints). Areas
covered: burst just over the limit, multi-key fairness, IPv6 vs IPv4 identity,
window boundary behavior, reset after the window, limit of 0, and concurrent
bursts.

Result: 3 breaks found, all fixed and tested. 0 fixed but failing. 0 blocked.
Two scoped areas held up and were left alone: burst just over the limit,
multi-key fairness, reset after window, and concurrent bursts all behaved
correctly; the fixed-window boundary doubling is documented design, not a bug.

## Finding 1 (high): limit of 0 silently became the default limit

What broke: constructing `RateLimitMiddleware(app, requests_per_minute=0)`
set the effective limit to 120 instead of 0, so every request passed. The
constructor used `requests_per_minute or settings.RATE_LIMIT_PER_MINUTE`, and
0 is falsy in Python.

How to reproduce: build the middleware with `requests_per_minute=0` and send
one request. Before the fix the constructor reported `limit == 120` and the
request returned 200; the probe printed `constructor limit value: 120` and
`first request status: 200`.

Root cause: `app/core/rate_limiter.py` in `__init__` (the `or` default).

Fix: explicit `None` check, so only an absent argument takes the default and
0 means refuse everything.

Test results: new `test_limit_of_zero_refuses_every_request` failed before
the fix (observed 200 where 429 was expected) and passes after. Full file
suite: 23 passed.

## Finding 2 (high): same client got two budgets via IPv4-mapped IPv6

What broke: `_client_id` canonicalized `::ffff:1.2.3.4` to itself instead of
to `1.2.3.4`, so one host reachable over both address families spent from
two separate shared buckets (pre-auth ceiling and public-MCP buckets),
doubling its budget. The non-Railway peer path was not canonicalized at all,
so equivalent spellings of one peer address also named different buckets.

How to reproduce: with `RAILWAY_ENVIRONMENT_ID` set, alternate requests with
`X-Real-IP: 1.2.3.4` and `X-Real-IP: ::ffff:1.2.3.4`, each with a distinct
invented API key, at `requests_per_minute=2` (shared ceiling 20). Before the
fix the 21st request still returned 200 (two buckets of 20); after the fix it
returns 429.

Root cause: `app/core/rate_limiter.py` in `_client_id` (no mapped-address
collapse, raw peer passthrough).

Fix: new `_canonical_host` helper that compresses the address and collapses
IPv4-mapped IPv6 to IPv4; both the Railway header path and the peer path use
it. Unparseable header values still fall back to the peer address, so garbage
values cannot mint fresh budgets.

Test results: new `test_client_id_canonicalizes_equivalent_addresses` and
`test_alternating_ipv4_and_mapped_ipv6_share_one_budget` fail before the fix
(probe showed `equal: False`) and pass after. Full file suite: 23 passed.

## Finding 3 (medium): limit of 0 crashed the in-memory reservation path

What broke: with the constructor fixed but nothing else changed, the first
request through `_reserve` raised `IndexError` instead of returning 429. When
the limit is 0, the live-entry list is empty and the code read `live[0]` to
compute the reset time.

How to reproduce: same setup as Finding 1. The new regression test failed
with `IndexError: list index out of range` at the `live[0]` line before this
fix.

Root cause: `app/core/rate_limiter.py` in `_reserve` (unguarded `live[0]`).

Fix: use the oldest live entry when one exists, otherwise the current time,
which reports a full window for reset purposes.

Test results: `test_limit_of_zero_refuses_every_request` passes after the
fix. Full file suite: 23 passed. Related suite
`tests/test_runtime_degradation.py`: 9 passed. `ruff check` on both touched
files passes. `mypy app/core/rate_limiter.py` is clean.

## Areas probed with no break

Burst just over the limit: request number limit+1 returns 429 on both
backends, remaining counts down correctly. Multi-key fairness: an exhausted
key returns 429 while a fresh key returns 200. Reset after window: budget is
fully restored once entries age out. Concurrent bursts: 15 simultaneous
requests at limit 5 admitted exactly 5. Invalid credentials, whitespace
variants of keys, and key rotation all stay bounded by the shared bucket.

## Not fixed (documented behavior)

Fixed-window boundary doubling: on the Redis backend, up to the full limit
can pass in the last instant of one 60-second window and again in the first
instant of the next, so roughly twice the limit fits in a 2-second span. The
in-memory fallback counts a rolling window and does not have this shape. The
discovery payload already discloses this difference, so changing the Redis
counting algorithm was out of scope for this task.

## Open questions

1. Should `RATE_LIMIT_PER_MINUTE=0` via environment be treated as refuse-all
   too, or rejected at startup as a misconfiguration? Currently the settings
   path accepts it and the middleware now honors it.
2. Should the fixed-window Redis counter move to a rolling window to match
   the fallback? That is a larger change with cross-instance semantics and
   needs C.Lee's call.
3. The in-memory sweep only runs once per window past 1024 buckets, so a fast
   key-rotation flood inside one window still grows memory until the window
   turns over. Is that acceptable, or should there be a hard cap?
