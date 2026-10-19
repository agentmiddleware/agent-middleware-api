# Schema 050: demo-key first use and funnel view

Migration `050_demo_key_first_used` revises `049_demo_key_attribution`. It is
additive:

| Change | Detail |
| --- | --- |
| `api_keys.first_used_at` | TIMESTAMP (naive UTC), nullable |
| Backfill | `UPDATE api_keys SET first_used_at = last_used_at WHERE first_used_at IS NULL AND last_used_at IS NOT NULL` |
| View `demo_key_funnel_by_source` | Read-only aggregate over `api_keys WHERE tenant = 'demo'` |

The backfill writes only the new column and deletes nothing. For keys used
before 050, `first_used_at` therefore holds the *last* use seen before the
migration, not the true first use. That is enough for "used vs. never used".

After 050, every authenticated key use sets `first_used_at` only while it is
NULL (`COALESCE` inside the guarded UPDATE for bounded and derived keys, an
`IS NULL` check on the ORM path for unbounded keys). Later calls never change
it.

## Querying the view

```sql
SELECT utm_source, utm_medium, utm_campaign, referrer_host,
       keys_issued, keys_used, first_issued_at, last_issued_at
FROM demo_key_funnel_by_source
ORDER BY keys_issued DESC;
```

Columns: `utm_source` (`'(none)'` when absent), `utm_medium`, `utm_campaign`,
`referrer_host` (host of an absolute referrer URL, otherwise the raw
referrer), `keys_issued` (count), `keys_used` (count with `first_used_at IS
NOT NULL`), `first_issued_at`, `last_issued_at` (min/max `created_at`).

On PostgreSQL with `TENANT_RLS_MODE=enforce`, `api_keys` has FORCE row-level
security, so the view returns no rows unless the session bypasses it. Run
the query inside a transaction as an operator:

```sql
BEGIN;
SELECT set_config('app.rls_bypass', 'on', true);
SELECT * FROM demo_key_funnel_by_source ORDER BY keys_issued DESC;
COMMIT;
```

On non-PostgreSQL databases (SQLite in tests) the view groups by the raw
referrer, because there is no portable host extraction.

The same numbers are available over HTTP, without database access:
`GET /v1/admin/demo-keys/funnel?since=2026-10-01T00:00:00Z&until=2026-11-01T00:00:00Z`
(bootstrap admin only). `since` is inclusive and `until` is exclusive, both
applied to issuance time.

## Compatibility release

Same rule as [schema-049-rollout.md](schema-049-rollout.md): boot refuses a
database revision that differs from the packaged head. Ship the image that
packages `050_demo_key_first_used` and apply 050 together. An image that
packages 049 cannot write `first_used_at` and cannot restart against a 050
database.

| Required record | Status |
| --- | --- |
| Schema 049 applied first per its own rollout gate | REQUIRED / UNVERIFIED |
| Target database revision and packaged head: `050_demo_key_first_used`; private parity result | REQUIRED / UNVERIFIED |
| Rehearsal: 049 → 050 on disposable PostgreSQL; backfill count matches `last_used_at IS NOT NULL`; view query above returns rows | REQUIRED / UNVERIFIED |

## Rollback

Downgrade drops the view, then `first_used_at`. Recorded first-use times are
lost. A 049-packaged image cannot restart against a 050 database, so never
downgrade a database that still serves traffic.

SQLite only: a later migration that rebuilds `api_keys` with
`batch_alter_table` must drop and recreate this view around the rebuild,
because SQLite refuses to rename a table that a view depends on mid-rebuild.
