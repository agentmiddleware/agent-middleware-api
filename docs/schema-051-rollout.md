# Schema 051: API key usage tracking

Migration `051_api_key_usage_events` revises `050_demo_key_first_used`. It is
additive:

| Change | Detail |
| --- | --- |
| `api_key_usage_events` table | Append-only event log: `id`, `key_id`, `tenant`, `method`, `route_template`, `status_code`, `latency_ms`, `created_at` |
| Index | `ix_api_key_usage_events_key_id_created_at` on `(key_id, created_at)` |
| View `api_key_usage_daily` | Read-only aggregate: `key_id`, `day_utc`, `calls`, `count_4xx`, `count_5xx`, `p50_latency_ms`, `p95_latency_ms`, `first_call`, `last_call` |

The migration creates the table, index, and view. No backfill is required.
After 051, every authenticated API call records one row in
`api_key_usage_events` asynchronously via background task. A failed write never
fails the request.

## Querying the view

```sql
SELECT key_id, day_utc, calls, count_4xx, count_5xx,
       p50_latency_ms, p95_latency_ms, first_call, last_call
FROM api_key_usage_daily
WHERE key_id = 'apk_...'
ORDER BY day_utc DESC
LIMIT 30;
```

Columns: `key_id` (FK to `api_keys.id`), `day_utc` (date), `calls` (total
count), `count_4xx` (4xx status codes), `count_5xx` (5xx status codes),
`p50_latency_ms` / `p95_latency_ms` (median and 95th percentile request
latency), `first_call` / `last_call` (min/max `created_at` timestamp for that
day).

On PostgreSQL with `TENANT_RLS_MODE=enforce`, `api_keys` and
`api_key_usage_events` have FORCE row-level security, so the view returns no
rows unless the session bypasses it. Run the query inside a transaction as an
operator:

```sql
BEGIN;
SELECT set_config('app.rls_bypass', 'on', true);
SELECT * FROM api_key_usage_daily
WHERE key_id = 'apk_...'
ORDER BY day_utc DESC;
COMMIT;
```

On non-PostgreSQL databases (SQLite in tests) the view uses SQLite-compatible
percentile syntax.

The same data is available over HTTP, without database access:
`GET /v1/api-keys/usage/daily?key_id=apk_...&since=2026-10-01&until=2026-11-01`
(bootstrap admin only; demo keys 403). `since` is inclusive and `until` is
exclusive, both applied to `day_utc`.

## Compatibility release

Same rule as [schema-050-rollout.md](schema-050-rollout.md): boot refuses a
database revision that differs from the packaged head. Ship the image that
packages `051_api_key_usage_events` and apply 051 together. An image that
packages 050 cannot record usage events and cannot restart against a 051
database.

| Required record | Status |
| --- | --- |
| Schema 050 applied first per its own rollout gate | REQUIRED / UNVERIFIED |
| Target database revision and packaged head: `051_api_key_usage_events`; private parity result | REQUIRED / UNVERIFIED |
| Rehearsal: 050 → 051 on disposable PostgreSQL; view query above returns rows after recording test events | REQUIRED / UNVERIFIED |

## Rollback

Downgrade drops the view, index, and table. All recorded usage events are lost.
A 050-packaged image cannot restart against a 051 database, so never downgrade
a database that still serves traffic.

SQLite only: a later migration that rebuilds `api_keys` with
`batch_alter_table` must drop and recreate this view around the rebuild,
because SQLite refuses to rename a table that a view depends on mid-rebuild.
