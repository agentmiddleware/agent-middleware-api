# Staging pilot: `delivery_uncertain` reconcile worker

Staging only. Production defaults stay off:

- `UPSTREAM_RECONCILE_WORKER_ENABLED=false`
- `UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED=false`
- `MCP_UPSTREAM_STATUS_URL=""`

This pilot turns the worker on for `api-service-staging` and points it at the
refund-partner fixture's `POST /status`. The refund flag stays false, so an
`executed` answer leaves the debit in place. The worker never redispatches a
parked call and never releases its budget because the row got old.

Design: [delivery-uncertain-reconcile-worker.md](delivery-uncertain-reconcile-worker.md).
The fixture deploy is [refund-partner-staging.md](refund-partner-staging.md).

## Railway variables (`api-service-staging` only)

Record the current values first. Set these two. Leave
`UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED` false (unset, or an
explicit `false`).

| Variable | Value |
| --- | --- |
| `UPSTREAM_RECONCILE_WORKER_ENABLED` | `true` |
| `MCP_UPSTREAM_STATUS_URL` | `https://<refund partner host>/status` |
| `UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED` | `false` |

`<refund partner host>` is the hostname already used in `MCP_UPSTREAM_URL`
(`https://<refund partner host>/mcp`). The status URL must share that origin.
The probe sends `MCP_UPSTREAM_BEARER_TOKEN`, which is the fixture's
`MCP_REFUND_PARTNER_BEARER_TOKEN`.

```sh
railway variables --service api-service-staging --environment staging \
  --set "UPSTREAM_RECONCILE_WORKER_ENABLED=true" \
  --set "MCP_UPSTREAM_STATUS_URL=https://<refund partner host>/status"
```

Railway restarts the service when the variables change. The worker runs inside
`periodic_cleanup`, whose first pass is 5 minutes after process start and
every 5 minutes after that. A parked row is due only after the first backoff
step (default 30 seconds).

## Produce a `delivery_uncertain` call

Call the governed tool with `after_effect` set to `hang`. `hang_seconds` must
exceed the gateway's `MCP_UPSTREAM_CALL_TIMEOUT_SECONDS` (default 30). The
fixture default is 90. The effect row is committed before the hang, so the
gateway times out and parks the call while the partner still holds the
response.

```json
{
  "jsonrpc": "2.0",
  "id": "staging-hang-1",
  "method": "tools/call",
  "params": {
    "name": "<MCP_UPSTREAM_PUBLIC_TOOL_ID>",
    "arguments": {
      "refund_ref": "staging-hang-1",
      "amount_cents": 100,
      "after_effect": "hang",
      "hang_seconds": 90
    },
    "mcpContext": {
      "wallet_id": "<agent wallet>",
      "permit_id": "<permit for the refund tool>",
      "idempotency_key": "staging-hang-1"
    }
  }
}
```

`POST /mcp/messages` returns JSON-RPC `-32005` with `message`
`delivery_uncertain` and a signed receipt whose `outcome` is
`delivery_uncertain`. `GET /__stress/effects` on the fixture (control header)
shows one effect row for that invocation.

## What to watch

On `api-service-staging`:

- `mcp_delivery_uncertain_aged` — one warning per process for an unresolved
  parked call older than `UPSTREAM_RECONCILE_ALERT_AGE_SECONDS` (default 3600).
  With this status URL pointed at the same tool and origin, `manual_review`
  is false.
- `cleanup_completed` — emitted by the 5-minute loop when a sweep probes,
  alerts, refunds, or repairs an audit. Read `delivery_uncertain_probed` and
  `delivery_uncertain_resolved`.
- Audit event `mcp_delivery_uncertain_provider_resolution` — one signed,
  hash-chained event per resolved attempt (`audit-ur-<attempt_id>`). For this
  pilot the metadata has `provider_outcome` `executed`, `reconcile_status`
  `executed`, and `budget_action` `none`.

The worker also logs `mcp_delivery_uncertain_resolved` for that row.

## Success criteria

- The attempt stays `state=delivery_uncertain` and gains
  `reconcile_status=executed`.
- The debit is still there: `debit_refunded_at` is empty, no refund ledger
  entry, permit spend unchanged.
- The signed receipt is the original `delivery_uncertain` receipt.
- a retry with the same key returns the original receipt instead of dispatching again.
- The fixture still has one effect row for that invocation.

## Rollback

Unset `UPSTREAM_RECONCILE_WORKER_ENABLED` and `MCP_UPSTREAM_STATUS_URL` on
`api-service-staging`. Leave
`UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED` false. Parked rows stay
in manual review. The refund-partner service can stay or be removed; restoring
the echo upstream is the rollback in
[refund-partner-staging.md](refund-partner-staging.md).
