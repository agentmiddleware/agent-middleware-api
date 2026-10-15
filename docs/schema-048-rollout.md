# Schema 048: wallet row-level security policies

Migration `048_tenant_rls` revises `046_demo_tenant_key_allowlist`. The
number 047 is held by `047_dispatch_reconcile_lease` on the unmerged reconcile
branch; 048 does not depend on its columns, and whichever of the two lands
second must re-parent onto the other so the tree keeps a single head. It is
PostgreSQL only and a no-op on
SQLite. It creates the `amw_tenant_isolation` policy on each wallet-scoped
table and the SELECT-only `amw_delegated_issuer_read` policy on `receipts`,
`ledger_entries`, `mcp_dispatch_attempts`, and `idempotency_records`. No
columns, rows, or indexes change.

Row-level security itself is **not** enabled by default. `ENABLE` and `FORCE
ROW LEVEL SECURITY` run only when the migration executes with
`TENANT_RLS_MODE=enforce`; with the default `off`, the policies exist but are
inert for every client, so the previously serving image and any other client
(psql, scripts, backups) behave exactly as before. Full design, runtime role
SQL, and the enforce rollout are in [tenant-rls.md](tenant-rls.md).

## Release prerequisites and compatibility

This document records prerequisites, not permission to deploy or evidence of
an operational rollout. Staging and production state have not been
inspected.

| Required record | Status |
| --- | --- |
| Current database revision and current packaged head; private parity result | REQUIRED / UNVERIFIED |
| Target database revision and packaged head: `048_tenant_rls`; private parity result | REQUIRED / UNVERIFIED |
| Schema 046 (`046_demo_tenant_key_allowlist`) applied first per its own rollout gate | REQUIRED / UNVERIFIED |
| Rehearsal: 046 → 048 upgrade on disposable PostgreSQL with `TENANT_RLS_MODE` unset; `relrowsecurity` false on every covered table | REQUIRED / UNVERIFIED |
| `TENANT_RLS_MODE` stays `off` through the release | REQUIRED / UNVERIFIED |

1. Verify the actual database revision and the serving image's packaged
   schema. 048 requires 046.
2. Apply 048 through the reviewed migration entrypoint with
   `TENANT_RLS_MODE` unset or `off`. Confirm the boot log line
   `phase="tenant_rls_posture"` shows `tables_with_rls_enabled=[]`.
3. Turning enforcement on is a separate, later step (runtime role, then the
   `enable_rls_statements()` ALTERs, then `TENANT_RLS_MODE=enforce`); see
   [tenant-rls.md](tenant-rls.md#rollout).

## Rollback after activation

With `TENANT_RLS_MODE=off` there is nothing to roll back operationally: RLS
is disabled and the policies are inert. If enforcement was turned on, set
`TENANT_RLS_MODE=off` first; the app then opts out per transaction while RLS
stays enabled. Alembic `downgrade` from 048 to 046 drops both policies and
runs `NO FORCE` / `DISABLE ROW LEVEL SECURITY` on every covered table. It is
schema-only and loses no data.
