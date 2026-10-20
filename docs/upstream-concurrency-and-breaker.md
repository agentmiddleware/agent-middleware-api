# Upstream concurrency limit and circuit breaker

Two optional, process-local controls on the governed upstream MCP dispatch
path. Both are off by default. With the defaults, a call is not admitted
through this gate, and dispatch, debit, and receipt behavior are unchanged.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM` | `0` | Maximum in-flight calls to one upstream in this process. `0` means unlimited (the limit is not applied). |
| `UPSTREAM_CIRCUIT_BREAKER_ENABLED` | `false` | When `false`, failures are not counted and the breaker cannot refuse a call. |
| `UPSTREAM_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Counted failures that open the breaker. A counted success while it is closed lowers that count by one. Used only when the breaker is enabled. |
| `UPSTREAM_CIRCUIT_BREAKER_RECOVERY_SECONDS` | `30` | How long an open breaker stays open before one trial call is allowed. |

Defined in `app/core/config.py`. The gate is `app/services/upstream_admission.py`.
It uses `CircuitBreaker` in `app/core/resilience.py`.

## Where the check runs

Only for `execution_backend == "upstream_mcp"`, and only when at least one
control is enabled. The check is inside `_execute_registered_tool_inner`,
after permit validation and before the enterprise IGA use, the wallet
re-plan reservation, permit budget reservation, the debit, and the dispatch
claim.

A refusal therefore does not reserve budget, does not debit, does not
dispatch, and does not mint a receipt. The in-progress idempotency record
is abandoned so the same key can be presented again.

Completed calls are unchanged: a retry with the same key returns the original receipt instead of dispatching again.

## Concurrency limit (per process)

The limit is an `asyncio.Semaphore` keyed by the upstream base URL
(`upstream_origin`, one trailing slash removed). If the origin is missing,
the key is the registered `service_id`. Two tools on the same origin share
one semaphore. Tools on different origins do not.

The semaphore lives in the process that admitted the call. A second
worker, process, or host has its own counter. This is not a cluster-wide
cap.

When the semaphore is full the call does not wait. The JSON-RPC error is
`-32005` with message `upstream_concurrency_saturated` and
`data.retry_after_seconds` of `1`. That number is a hint that the client
should back off briefly. A slot may free sooner. The REST invoke surface
returns HTTP 503 with the same reason and hint.

The slot is released when the invocation finishes, including when it
raises and when the task is cancelled. Release is synchronous
(`Semaphore.release`) from the `finally` of `_run_inner_settling_replan_guard`,
so it still runs if cancellation arrives while another cleanup step is
awaiting.

## Circuit breaker (per process)

One breaker per upstream key, again only inside this process. While it is
closed, calls pass. After the failure threshold it opens and further calls
fail fast with `-32005`, message `upstream_circuit_open`, and
`retry_after_seconds` set to the remaining recovery window (at least 1).
When that window has elapsed the breaker half-opens and allows one trial
call. A trial that reaches the upstream and gets a normal answer (success
or a tool-level error result) closes the breaker. A trial that is a
counted failure opens it again.

### What counts as a failure

- A transport failure or timeout **before** the dispatch checkpoint. The
  adapter reports that as `upstream_pre_dispatch_failed`.
- A `delivery_uncertain` outcome **after** the dispatch checkpoint. The
  call may have been delivered, so it is evidence the upstream is in
  trouble.

Recording `delivery_uncertain` does not change that call. The debit
stands, the signed receipt stays `delivery_uncertain`, the budget is not
released, and the gateway does not redispatch it.

These do **not** count:

- A tool-level error (`upstream_returned_error`): the upstream answered.
- A dispatch-checkpoint failure (`upstream_dispatch_checkpoint_failed`):
  that is this process failing to claim the send, not the upstream
  failing the transport.
- A response the gateway rejects after the upstream has already answered
  (`response_rejected`).
- A call that is refused or cancelled before the upstream is contacted.
  The slot is released and the breaker is left as it was.

## What this does not do

- It does not coordinate limits or failure counts across processes.
- It does not refund or redispatch a `delivery_uncertain` call.
- It does not change `RETRY_LOOP_ALERT_ENABLED` or `WALLET_REPLAN_GUARD`.
