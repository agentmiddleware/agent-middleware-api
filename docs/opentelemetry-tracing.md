# Optional OpenTelemetry tracing

Tracing is off unless an operator turns it on. The default deployment does
not install the OpenTelemetry packages and does not emit spans.

## Settings

| Setting | Default | Role |
| --- | --- | --- |
| `OTEL_TRACING_ENABLED` | `false` | Master switch. `false` configures no tracer and adds no middleware. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | OTLP HTTP base URL, usually port `4318`. The exporter posts traces to `{endpoint}/v1/traces`. |
| `OTEL_SERVICE_NAME` | `agent-middleware-api` | Resource attribute `service.name`. |

`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, when set in the environment and
`OTEL_EXPORTER_OTLP_ENDPOINT` is empty, is read by the OTLP HTTP exporter
itself. The endpoint is never copied onto a span.

## Install

The packages are the `otel` extra in `pyproject.toml` and are listed in
`requirements-dev.txt` so tests can run. They are not in `requirements.txt`,
and the production image does not install them.

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

If `OTEL_TRACING_ENABLED=true` but those imports fail, startup continues
with tracing left off.

## Spans

When tracing is on, one HTTP request span parents the governed invoke, and
the invoke parents the phase spans that actually run:

- `http.request` — ASGI middleware, added only while tracing is on. It does
  not read the body, and it does not record the method, path, headers, or
  body. This app does not install FastAPI's OpenTelemetry instrumentation,
  so route and dependency spans are not emitted.
- `mcp.invoke` — `McpGovernedAdapter.invoke`.
- `mcp.reserve` — permit budget reserve (`authorize_and_reserve` or
  `authorize_reserve_and_prepare`).
- `mcp.dispatch_claim` — durable claim of the one upstream send.
- `mcp.upstream_dispatch` — the upstream `tools/call`. While this span is
  current, the pinned HTTP transport adds a W3C `traceparent` (and
  `tracestate` when the propagator sets one) if the request headers accept
  assignment. A client that refuses the write still dispatches.
- `mcp.receipt` — the signed receipt write on the MCP path.

A tracer, provider, or span-processor failure while starting a span,
entering or leaving it, writing an attribute, ending it, or injecting
`traceparent` is logged once at debug and ignored. The governed code still
runs once, and an exception it raises propagates unchanged. That failure
does not change the permit, charge, dispatch, or receipt result, and it
cannot mark a call that was not sent as `delivery_uncertain`. Idempotency
is unchanged: a retry with the same key returns the original receipt instead of dispatching again.
Tracing does not release budget and does not redispatch a `delivery_uncertain`
row.

## Attributes

Only these attributes are recorded:

- `tool.name`
- `outcome.state`
- `wallet.id_hash` — SHA-256 hex of the wallet id, not the id itself
- `attempt.id`

Values that are not short printable tokens are dropped. Secrets, API keys,
authorization headers, request bodies, and tool arguments are not span
attributes, and exception messages are not recorded on the span.
