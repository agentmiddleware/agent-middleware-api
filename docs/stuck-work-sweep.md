# Stuck-work sweep

Status: **shipped, on by default**. Logs only, plus an expired-lease
**alert**. It does not clear lease columns, move money, release budget, or
redispatch.

Runs from `periodic_cleanup` in `app/main.py` on the same 5-minute loop as
the other maintenance passes. It does **not** consult
`UPSTREAM_RECONCILE_WORKER_ENABLED`. The per-row
`mcp_delivery_uncertain_aged` log inside
`DeliveryUncertainReconcileWorker` still runs only when that worker is on.

## What it alerts on

One structured warning, event name `stuck_work_alert`, when any count below
is non-zero. Fields:

| Field | Meaning |
|---|---|
| `delivery_uncertain_aged` | Unresolved `delivery_uncertain` rows parked at least `STUCK_WORK_UNCERTAIN_ALERT_AGE_SECONDS` (default 3600). Parked time is `coalesce(completed_at, updated_at)`. Rows that already have a `reconcile_status` are excluded. |
| `delivery_uncertain_oldest_age_seconds` | Age of the oldest row in that set. |
| `delivery_uncertain_buckets` | Cumulative counts at 1×, 6×, and 24× the configured age: `ge_1x`, `ge_6x`, `ge_24x`. With the default age those buckets are 1 hour, 6 hours, and 24 hours. |
| `expired_lease_count` | Rows with `reconcile_lease_owner` set and `reconcile_lease_expires_at` strictly older than `now - STUCK_WORK_LEASE_GRACE_SECONDS` (default grace 300). Emitted only when `STUCK_WORK_LEASE_REAPER_ENABLED` is true. |
| `idempotency_needs_review` | Idempotency records older than the same age threshold that `IdempotencyService.reconcile_stuck_records` would count for manual review: no stored response, a ledger debit or `operation_kind=awi_http`, no dispatch attempt, and no receipt. |
| `idempotency_needs_review_oldest_age_seconds` | Age of the oldest such record. |
| `leases_cleared` | Always `0`. |
| `lease_reaper` | Always `alert_only`. |

The total-count `mcp_dispatch_operator_alert` log is unchanged. This sweep
adds the age buckets that log does not carry.

## Why expired leases are not cleared

`DeliveryUncertainReconcileWorker._due_conditions` already treats a lease as
free when `reconcile_lease_expires_at` is null **or** `<= now`. `claim_due_calls`
writes the new owner with a conditional `UPDATE` that re-checks that same
predicate, so two sweeps cannot both own the row, and a crashed sweep's
leftover `reconcile_lease_owner` / `reconcile_lease_expires_at` does not block
the next claim once the lease time has passed.

A conditional `UPDATE` that nulled those columns after a grace window would
not free any additional row. It would also be a write on the attempt during
a path that must not touch state. `STUCK_WORK_LEASE_REAPER_ENABLED` (default
true) therefore only gates the count. A lease that has not yet reached
`now - grace` is not included, so a holder still inside the grace window is
not reported as stuck. A holder whose expiry is still in the future is not
free for claim and is not alerted here.

## What it does not do

- It does not change `mcp_dispatch_attempts.state`.
- It does not refund a debit, insert a ledger row, or change a wallet balance.
- It does not release permit budget. Age is not a reason to release a
  reservation on a `delivery_uncertain` call.
- It does not redispatch. Idempotency copy, where a receipt exists: "a retry with the same key returns the original receipt instead of dispatching again".
- It does not complete or delete idempotency records. The existing
  `reconcile_stuck_records` pass in `periodic_cleanup` still does repair;
  this sweep only counts what that pass leaves for review, and only once
  those rows are older than the age threshold.
- It does not turn on `UPSTREAM_RECONCILE_WORKER_ENABLED` or
  `UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED`.

## Settings

| Setting | Default | Effect |
|---|---|---|
| `STUCK_WORK_SWEEP_ENABLED` | `true` | Master switch. Off: no query, no log. |
| `STUCK_WORK_UNCERTAIN_ALERT_AGE_SECONDS` | `3600` | Age threshold for both `delivery_uncertain` and idempotency review. Range 1…2592000. |
| `STUCK_WORK_LEASE_GRACE_SECONDS` | `300` | Extra wait after lease expiry before the lease alert. Range 0…86400. |
| `STUCK_WORK_LEASE_REAPER_ENABLED` | `true` | Gates the expired-lease **alert**. Does not null lease columns. |

`RETRY_LOOP_ALERT_ENABLED` stays off. `WALLET_REPLAN_GUARD` stays `log_only`.
