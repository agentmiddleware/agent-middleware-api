# Schema 047: delivery_uncertain reconcile lease columns

Migration `047_dispatch_reconcile_lease` revises
`046_demo_tenant_key_allowlist`. It adds six columns to
`mcp_dispatch_attempts`, all nullable except a zero-defaulted counter:

| Column | Type | Meaning |
| --- | --- | --- |
| `reconcile_status` | VARCHAR(32), indexed | NULL = unresolved (manual review); `executed`, `not_executed_review`, `not_executed_refund_pending`, `not_executed_refunded` |
| `reconcile_lease_owner` | VARCHAR(64) | random per-sweep owner id; not a credential |
| `reconcile_lease_expires_at` | DATETIME, indexed | lease expiry |
| `reconcile_next_probe_at` | DATETIME, indexed | durable backoff |
| `reconcile_probe_count` | INTEGER NOT NULL DEFAULT 0 | probes performed |
| `reconciled_at` | DATETIME | when a terminal resolution was recorded |

No data migration and no backfill. `state` is never touched: existing
`delivery_uncertain` rows upgrade to `reconcile_status = NULL`, which is what
they mean today: parked for manual review. No credential or bearer token is
stored on these rows; the reconcile probe uses the operator-configured
`MCP_UPSTREAM_BEARER_TOKEN`.

The columns are also added to `REQUIRED_TRUST_COLUMNS`, so a production-like
boot against a 046 database fails closed instead of serving with an ORM model
the schema cannot satisfy. Apply 047 before rolling out the image that
contains it.

The columns back the default-off reconciler
(`UPSTREAM_RECONCILE_WORKER_ENABLED=false`); see
[delivery-uncertain-reconcile-worker.md](delivery-uncertain-reconcile-worker.md).

## Release prerequisites and compatibility

This document records prerequisites, not permission to deploy or evidence of
an operational rollout. Staging and production state have not been
inspected.

| Required record | Status |
| --- | --- |
| Current database revision and current packaged head; private parity result | REQUIRED / UNVERIFIED |
| Target database revision and packaged head: `047_dispatch_reconcile_lease`; private parity result | REQUIRED / UNVERIFIED |
| Rehearsal: 046 → 047 upgrade on disposable PostgreSQL, parked rows read back with NULL status and zero probe count | REQUIRED / UNVERIFIED |
| `UPSTREAM_RECONCILE_WORKER_ENABLED` and `UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED` stay `false` until separately authorized | REQUIRED / UNVERIFIED |

## Rollback

Downgrade from 047 to 046 drops the six columns and their indexes. It refuses
to run while any row has a non-NULL `reconcile_status`. A
`not_executed_refund_pending` row may hold a half-applied refund and budget
release. A `not_executed_refunded` row's refund and release are durable, but
046 accounting counts every `delivery_uncertain` receipt as consumed, so a
budget rebuild would re-charge the released spend. `executed` and
`not_executed_review` decisions would be erased and re-probed after a later
re-upgrade. In practice, once the reconciler has resolved any row, 047 is
forward-only; roll back by deploying a fix forward, not by downgrading. Never
downgrade a database that still serves traffic, and never stamp a revision to
skip the downgrade.
