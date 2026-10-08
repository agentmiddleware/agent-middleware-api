# Pilot observability

How to watch a pilot deployment and how to reconstruct an incident.

## Request IDs

Every HTTP response carries an `X-Request-ID` header. Send your own ID and
the gateway echoes it back; omit it (or send an unusable value) and the
gateway mints one. The same ID is attached to the server-side log lines
for that request and appears in 500 responses as `request_id`, so quote it
when reporting a failure.

Example:

```bash
curl -i http://127.0.0.1:8000/health
# x-request-id: 9f2c...

curl -i -H "X-Request-ID: pilot-call-123" http://127.0.0.1:8000/health
# x-request-id: pilot-call-123
```

## Logs

The gateway logs structured JSON to stderr. Each request produces one
`request finished` line with method, path, route template, status code,
latency, and request ID. Unhandled exceptions log a traceback server-side
only; the caller sees a fixed `internal_error` body with the request ID,
never exception text.

## Metrics

`GET /metrics` is public (no API key, like `/health`) and returns
process-local counters: total requests, total 5xx errors, uptime, and
per-route request, error, and latency figures.

```bash
curl http://127.0.0.1:8000/metrics
```

Limits, stated plainly: each worker keeps its own counters and every value
resets on restart, so do not sum across deploys or workers. Scraping
`/metrics` itself is not counted. There is no external error-tracking or
alerting integration; wire log-based alerts on 5xx rate at your collector
before a paid pilot.

## Incident recipe

1. Take the `request_id` from the failed response.
2. Find the matching `request finished` and error lines in the JSON logs.
3. Check `/metrics` for error rate and slow routes, and `/health/ready`
   plus `/health/dependencies` for dependency state.
4. No SLA, RTO, or RPO is claimed; see `docs/deploy-railway.md`.
