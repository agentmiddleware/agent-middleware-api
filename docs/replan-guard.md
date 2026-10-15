# Wallet re-plan guard

**Setting:** `WALLET_REPLAN_GUARD=off|log_only|enforce` (default `log_only`).
**Code:** `app/services/replan_guard.py`, `app/services/argument_canonicalizer.py`,
the gate in `app/routers/mcp.py::_execute_registered_tool_inner`.
**Tests:** `tests/test_argument_canonicalizer.py`, `tests/test_replan_guard.py`
(per-process store and a real local `redis-server`),
`tests/test_replan_guard_mcp.py` (end to end through `POST /mcp`).

## The hole it closes

Every other repeat control keys on something the agent can change:

- The idempotency key. A restarted agent that lost its key store mints a new one.
- The per-permit duplicate guard (`MCP_UPSTREAM_DUPLICATE_GUARD`) keys on
  `permit_id`.
- The permit budget is per permit.

`POST /mcp` auto-mints a fresh, single-tool permit for every call that
carries no `permit_id`. So an agent that re-plans the same action under a new
idempotency key got a new permit, a new budget, and a second dispatch and
debit. Nothing in the chain could see that it was the same action. This guard
keys on the wallet, which the caller cannot rotate.

## What it does

It runs on every governed call (local tools and the configured upstream
tool), after deterministic permit and wallet policy checks. It runs before
the advisory Jev check, the human-approval page, the budget reservation, the
debit, and the dispatch.

1. **Wallet-scoped dedup.** A lock on
   `(wallet_id, tool, canonical argument hash)` for
   `WALLET_DEDUP_WINDOW_SECONDS` (default 86400). The lock is the same across
   all of the wallet's permits, explicit or auto-minted. It is owned by the
   idempotency key that took it.
2. **Wallet velocity cap.** Two counters, summed across all of the wallet's
   permits in a fixed `WALLET_VELOCITY_WINDOW_SECONDS` window (default 3600):
   - credits, capped by `WALLET_VELOCITY_MAX_CREDITS` (default 10000; `0` means
     no cap);
   - calls, capped by `WALLET_VELOCITY_MAX_CALLS` (default 600; `0` means no
     cap).

   Credits are counted as exact integer minor units (10^-8 credit, the
   storage scale of `Numeric(20, 8)`) using `INCRBY`, never float. A cost
   finer than the storage scale rounds up.

The check and the record are one atomic step: a single Lua script on Redis,
or one critical section in the per-process store. Of N concurrent identical
re-plans, exactly one reserves
(`test_concurrent_identical_replans_reserve_exactly_once`).

### Outcomes

| Outcome of the governed call | Dedup lock | Velocity |
|---|---|---|
| Success | kept for the window | kept |
| Denied or failed before the debit commits (later policy gate, approval pending, budget, insufficient funds, cancellation) | released | refunded |
| Refunded deterministic failure after the debit (`upstream_returned_error`, `upstream_pre_dispatch_failed`, local tool raised and was refunded) | released | refunded |
| Charge stands (`delivery_uncertain`, `response_rejected`, unrefunded failure, unclassified error) | kept | kept |
| Another live activation of the same key owns the operation (`idempotency_in_progress`) | kept | kept |

Release and refund are one atomic script. A release deletes the lock only if
the releasing key still owns it. Counters never go below zero. The refund is
applied to the bucket the cost was recorded in, so a refund that lands after
a window rollover cannot decrement the new window.

Keeping the lock on `delivery_uncertain` is the point of the guard. The
gateway already refuses to redispatch that outcome under the same key. The
guard extends that refusal to a re-plan under a new key, for identical
arguments, within the window.

### Same-key retries

Same-key retries are unchanged. They replay the stored receipt through the
idempotency record before this gate runs. A same-key retry that does reach
the gate (its record was released because a retryable condition stopped it)
re-enters its own lock without counting velocity a second time.

## Canonicalization

Defined in `app/services/argument_canonicalizer.py`. The aim is that a
re-serialized copy of the same arguments hashes the same, and that anything a
tool could read differently does not.

- Object keys are sorted. Array order is kept.
- Every string, key or value, is Unicode NFKC-normalized.
- **No global lowercasing and no whitespace stripping.** `"Bob"` and `"bob"`
  are different requests.
- Case-folding (`str.casefold`) applies only to string values under fields
  named in `REPLAN_CASEFOLD_FIELDS`, for example `email,domain`. The default
  is empty, so nothing is folded unless an operator lists it.
- Numbers are normalized exactly through `Decimal`, with no float arithmetic.
  `1`, `1.0` and `1.00` are one number. A float from the JSON parser is read
  through its shortest round-trip `repr`. Non-finite numbers are refused.
- Types stay distinct: `true` is not `1`, and `"1"` is not `1`.
- Two keys that collide after NFKC are both kept, in a fixed order.
- The tool name is part of the hash. The permit id and the idempotency key are not.

## Modes

- `off`: not evaluated, nothing recorded.
- `log_only` (default): evaluated and recorded, and it **never blocks**. A
  would-be denial logs `replan_guard_would_deny` (WARNING, logger
  `app.services.replan_guard`) with the wallet, the tool, a hash prefix, the
  backend, and the reason code. Arguments and keys are never logged. Store
  outages, canonicalization errors, and unexpected exceptions are logged and
  the call proceeds. An allowed duplicate still counts toward velocity
  because it will run, but it never takes over another key's lock.
- `enforce`: refuses with a signed denial receipt, `outcome: denied`, and one
  of these reason codes:
  - `wallet_duplicate_request`. Details: `scope`, `window_seconds`,
    `canonical_request_hash`.
  - `wallet_velocity_exceeded`. Details: `limit` (`credits` or `calls`),
    `window_seconds`, and the limit, the current window value, and the
    requested value.

  As with every governed denial, the denied key is bound to its denial.

  If the guard cannot answer (the shared store is unreachable, or the
  arguments cannot be canonicalized), `enforce` **fails closed and
  retryable**: `wallet_guard_unavailable`, JSON-RPC `-32005` / HTTP 503, no
  receipt, nothing charged. The idempotency key is released so the same call
  can be retried once the store is back.

A permit with `allow_identical_repeats=true` skips the dedup half. The
velocity half still applies.

## Store

- If `REDIS_URL` is set, the guard uses one shared Redis, like the rate
  limiter. It does not use the durable-state backend: on the supported
  Postgres + Redis deployment, `shared_redis` returns None, which would make
  the guard per-process.
- Keys share a cluster hash tag per wallet, so the multi-key script is legal
  on Redis Cluster:

  ```text
  amw:{<wallet>}:dedup:<sha256>
  amw:{<wallet>}:vel:credits:<window-start>
  amw:{<wallet>}:vel:calls:<window-start>
  ```

  A wallet id that contains anything outside `[A-Za-z0-9_.:-]` is replaced in
  the tag by a hash of itself, so braces in an id cannot split a wallet's keys
  across slots. Every key has a TTL.
- Without `REDIS_URL`, the guard uses per-process counters. These bound one
  process only, so N replicas allow up to N times the cap and N concurrent
  duplicates.
- If `REDIS_URL` is set but Redis is unreachable:
  - production-like environments report the store unavailable (`enforce`
    denies retryably, `log_only` allows);
  - other environments fall back to per-process counters with a
    `replan_guard_memory_fallback` warning.

## Limits

- **This is not proof of non-duplication.** The guard recognizes repeats of
  identical canonical arguments for the same tool, from the same wallet,
  within the window. A re-plan that changes any argument value is a new
  request, for example a new free-text memo, a timestamp, or a reworded
  description. So is a call from a different wallet, or one after the window.
  Semantic equivalence is out of scope.
- The guard leaves the core guarantee unchanged: **at-most-once dispatch, not
  exactly-once execution.** It lowers how often a re-planning agent can
  repeat an identical action. It does not make a remote effect exactly once.
- Legitimate identical repeats inside the window are refused in `enforce`,
  for example polling the same read every minute. Use a shorter window,
  `allow_identical_repeats` on an explicitly issued permit, or leave the
  guard in `log_only`.
- The velocity cap counts each call's authorized cost (the registered or
  quoted price), not the final metered charge. It is a wallet guardrail, not
  a ledger. The ledger's daily limit remains the only hard daily-spend stop.
- Velocity windows are fixed buckets. A caller straddling a boundary can
  land up to twice the cap inside one arbitrary window span, the same
  accounting as the rate limiter.
- Under `enforce`, a refused keyless `POST /mcp` call still mints its
  short-lived auto-permit, because the denial receipt is signed against it.
  That permit's budget is never reserved, and it expires after
  `STANDARD_MCP_PERMIT_TTL_SECONDS`.
- Legacy unpermitted MCP calls (`ALLOW_LEGACY_UNPERMITTED_MCP=true`, refused
  in production) are not governed and are not evaluated.
- `/health/dependencies` does not report the guard's per-process fallback.
  Only the warning log does.
