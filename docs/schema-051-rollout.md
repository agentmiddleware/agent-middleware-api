# Schema 051: API key usage events

Migration `051_api_key_usage_events` revises `050_demo_key_first_used`. It adds
the metadata-only `api_key_usage_events` table, an index on `(key_id,
created_at)`, and the read-only `api_key_usage_daily` view. It changes no
existing rows. Usage before 051 is not backfilled; `api_keys.use_count` is a
bounded-key budget counter, not a historical call total.

## Compatibility release

Production boot requires the database revision to match the packaged Alembic
head. A 050-packaged image cannot restart after 051 is applied. Before applying
051, qualify a 051-compatible image and a recovery artifact against a
disposable PostgreSQL upgrade from 050. Verify the event insert, the daily
view, the admin-only read route, and enforced RLS with the intended runtime
role. Record the exact image SHA, database revision, and private parity result.
These release checks are required and have not been run in this worktree.

The new event writer is best effort: an insert failure leaves a reporting gap
without failing the API request. The view contains only events recorded after
the migration. The table's PostgreSQL policy allows only explicitly scoped
admin transactions when RLS is enforced; the application exposes the view
through a bootstrap-admin-only route.

## Rollback boundary

Do not deploy a 050-packaged image against schema 051. Use a qualified
051-compatible recovery image while retaining the database at 051. Alembic
downgrade to 050 drops the view and table, permanently discarding every usage
event recorded since 051. It is a data-loss operation, not an application
rollback; never perform it while the API serves traffic.
