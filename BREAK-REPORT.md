# BREAK-REPORT: app/middleware/ adversarial testing

## Summary

Probed auth middleware order, CORS edge cases for credentialed calls, request
id propagation, body read twice, and early disconnect with local ASGI tests
only. Result: 1 real break found, fixed, and tested. 0 fixed but failing.
0 blocked. The rest of the stack held up under every adversarial case tried,
and those negative results are recorded below so nobody re-probes them.

## Finding 1 (medium): request IDs were consumed but never assigned or bounded

What broke: several routers read the inbound `X-Request-ID` header and file
it on audit and billing-governance records (`app/routers/planner.py:63`,
`app/routers/billing.py:617`, `app/routers/sandbox.py`), yet no layer ever
assigned one. Responses never carried it back, so callers could not match a
request to a receipt or an error, and requests without the header left no
correlation handle at all. Worse, the raw header value flowed straight toward
the audit `request_id` column, which caps at 100 characters
(`app/db/models.py:705`), while `record_audit_event`
(`app/services/audit_log.py:84`) validates only `event_id`, never
`request_id`. A single overlong caller value could therefore fail the audit
write, and with it the request, on a length-enforcing database.

How to reproduce: send any request with `X-Request-ID: <200 chars>` and watch
the value pass through unmodified (pre-fix), or send none and observe that no
`x-request-id` appears on the response.

Root cause: missing boundary layer. No file assigned or normalized the ID;
`app/main.py` registered no such middleware.

Fix: new `app/middleware/request_id.py` (`RequestIdMiddleware`, pure ASGI,
registered outermost in `app/main.py`). It keeps the first inbound value of
1 to 128 safe characters, replaces anything else (absent, overlong, odd
characters, competing duplicates) with a generated `uuid4().hex`, rewrites
scope headers to exactly that one value, stashes it on `scope["state"]`, and
stamps it on every response out, including 413s, 429s, and CORS preflights.
`add_cors_middleware` now also sets `expose_headers=["X-Request-ID"]` so
credentialed browser callers can actually read it.

Test results: new `tests/test_request_id_middleware.py`, 13 tests, all pass.
Fail-without-fix confirmed two ways: with the middleware file moved aside the
file errors at collection, and with the `add_middleware` line commented out
the real-app registration test fails. Full fast suite after the fix: 4282
passed, 86 skipped, 746 deselected. `ruff check` clean, `ruff format` clean,
`mypy app/middleware/request_id.py` clean.

## Negative results (probed, held, no change made)

1. Wildcard CORS with credentials: `add_cors_middleware` forces
`allow_credentials=False` under `["*"]`, and tests confirm an arbitrary
Origin is never reflected with credentials. The installed Starlette 1.7
would otherwise echo the origin with credentials, so this guard is
load-bearing and intact.
2. 413 and 429 bodies carry CORS (`Access-Control-Allow-Origin`,
credentials) and security headers under the real registration order. An
early probe appeared to show bare 429s, but that probe had stacked the
layers in the wrong order; re-stacked like `app/main.py`, all headers are
present. No product change.
3. Body read twice: an endpoint calling `request.body()` twice then
`request.stream()` after `RequestBodyLimitMiddleware` replay sees intact
bytes. Multi-chunk streams coalesce exactly (1024-byte total across 3
chunks delivered whole), and mid-flight over-limit streams still 413
without `Content-Length`. No change.
4. Early disconnect: mid-body `http.disconnect` and immediate disconnect
behave byte-identically with and without the body-limit middleware
(downstream sees the same `ClientDisconnect` path). No change.
5. HEAD translation: HEAD with `Origin` returns the GET status and headers,
empty body, preserved `Content-Length`, and CORS headers. Auth still
enforces at the route since translation only changes the method the router
sees. No change.
6. Rate limiter under concurrency: 30 concurrent requests against a limit of
5 admitted exactly 5 and refused 25 in the in-memory backend. The
reserve-before-run design holds. No change.
7. Garbage `Authorization` values (`Bearer [REDACTED]`, `a.b.c`, non-JWT
schemes) are bucketed as invalid identities without raising, so the limiter
never 500s on malformed credentials. No change.
8. Auth bypass sampling (empty, whitespace, wrong-case, `Bearer`-prefixed,
and `null` API keys) found no acceptance path; all refused. Protected
billing routes are dormant in this boot (proof surfaces disabled), so this
was sampled on mounted surfaces plus unit-level credential parsing, not an
exhaustive auth audit. No change.

## Open questions

1. `SecurityHeadersMiddleware._is_secure` trusts a client-sent
`X-Forwarded-Proto` header whenever proxy-headers middleware is absent. A
plain-HTTP caller can therefore coax an HSTS header out of a non-TLS
response. Browsers ignore HSTS over HTTP, so impact looks nil, but the
trust basis is worth a second opinion before touching Railway behavior.
2. `add_cors_middleware` silently drops credentialed CORS when an operator
mixes `"*"` with explicit origins (wildcard wins, credentials off). This
matches the documented posture, but a startup warning on mixed lists would
catch misconfiguration earlier.
3. The preauth/rate-limit skip list matches exact paths (`/health` but not
`/health/ready`), so some health-adjacent endpoints burn rate budget. Fine
as is, but worth knowing when tuning monitor polling.
