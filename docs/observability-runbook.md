# Observability runbook

What to watch, where to look, and what to do when something fails. Written
for the operator on call, not the developer. Honest posture first: we make
no SLA, RTO, or RPO claim (see docs/deploy-railway.md). This runbook tells
you how to notice a problem and where the evidence lives.

## The three signals

| Signal | Where | What it tells you |
|---|---|---|
| Logs | stderr, structured JSON | One JSON object per line, ISO timestamps, every line carries `request_id` |
| Health | `/health`, `/health/ready`, `/health/dependencies` | Is it up, is it ready, which dependency is down |
| Metrics | `/metrics` | Request counts and average latency by route, Prometheus text format |
| Errors | Sentry, when `SENTRY_DSN` is set | Unhandled exceptions and failed startups, with alerting |

Unauthenticated endpoints: `/health`, `/health/ready`,
`/health/dependencies`, and `/metrics` need no API key, so load balancers
and uptime monitors can poll them. They carry no request contents, keys, or
tenant data.

## Request IDs

Every response carries an `X-Request-ID` header. The gateway accepts a
caller-supplied ID when it is a plain token (letters, digits, `.` `_` `~`
`-`, up to 128 chars) and mints one otherwise, so a hostile value can never
inject newlines into logs. The same ID is bound to every structured log
line for that request.

When a customer reports a failure, ask for their `X-Request-ID` response
header value, then grep the logs for `"request_id":"<value>"`. Without it,
filter by time window, route, and status instead.

## Health endpoint playbook

- `GET /health` returns 200 `healthy`, or 503 `degraded` when a configured
  Redis does not answer within 1 second. Action: check Redis, then check
  whether `REDIS_URL` is even supposed to be set on this deployment. No
  `REDIS_URL` means no Redis check, which is normal for small instances.
- `GET /health/ready` returns 200 `ready`, or 503 naming the failing check
  (`state_store`, `mqtt`, `database`). Action: read the named check first.
  `mqtt` reports `not_used` while `iot_bridge` is simulated, which is
  normal, not a failure.
- `GET /health/dependencies` probes each dependency with a 2 second
  timeout and reports `latency_ms` plus an error code per entry. Driver
  messages stay server-side; the endpoint returns only the exception class.
  Action: match the failing entry to its service, then read the server log
  for the full error text.

## Metrics playbook

- `GET /metrics` exposes `amw_http_requests_total` (by route and status),
  `amw_http_request_latency_seconds_avg` (by route), and
  `amw_process_uptime_seconds`. Scrape it with Prometheus or any
  plain-text collector.
- Counters are process-local and reset on every restart or redeploy. A
  graph that drops to zero at a deploy boundary is expected, not data
  loss. There is no durable request history yet; treat `/metrics` as a
  current-process signal, not an audit trail.
- Suggested first alerts: 5xx rate above baseline on the permit to receipt
  routes, average latency climbing on any money-path route, and process
  restarts (uptime resetting unexpectedly often).

## Error tracking

- Off by default. Set `SENTRY_DSN` (and optionally
  `SENTRY_TRACES_SAMPLE_RATE`, default 0.0 for errors only) to report
  unhandled exceptions and failed startups to Sentry. Without the
  `sentry-sdk` package installed, the API logs a warning at startup and
  continues with logs only.
- The startup log line `phase="runtime_posture"` records
  `error_tracking_enabled=true/false`, so you can confirm from logs alone
  whether a deployment reports anywhere.
- Suggested Sentry alerts: any 5xx exception event, and any
  `app_startup_failed` event (the gateway failed to boot).

## Startup and shutdown logs

- `phase="runtime_posture"` logs environment, proof-surface flags,
  simulation modes, and backend readiness with timings. Read this first
  when a fresh deploy misbehaves.
- `app_startup_failed` with a `remediation` field names the fix for
  signing-key and configuration boot failures. Follow the remediation
  text before anything else.
- `mcp_dispatch_operator_alert` during periodic cleanup names uncertain
  dispatches needing reconciliation. These are money-path states, treat
  them as higher priority than generic dependency warnings.

## Naming note: product telemetry is not monitoring

`/v1/telemetry/*` and `/v1/telemetry-scope/*` are a frozen product proof
surface (autonomous PM anomaly detection on customer data), not
operational monitoring of this API. Do not point an uptime monitor at
them, and do not describe them as monitoring to buyers. Operational
visibility lives in the four signals at the top of this page.
