# Schema 049: demo-key UTM and referrer attribution

Migration `049_demo_key_attribution` revises `048_tenant_rls`. It adds six
nullable columns to `api_keys` and nothing else:

| Column | Type |
| --- | --- |
| `utm_source` | VARCHAR(128), nullable |
| `utm_medium` | VARCHAR(128), nullable |
| `utm_campaign` | VARCHAR(128), nullable |
| `utm_content` | VARCHAR(128), nullable |
| `utm_term` | VARCHAR(128), nullable |
| `referrer` | VARCHAR(512), nullable |

Existing rows are untouched: every key issued before this migration, including
demo keys, keeps NULL on all six columns. Only `POST /v1/demo/keys` writes
them, and only for fields the caller actually supplied. Keys minted any other
way stay NULL. No data migration, no default that rewrites rows, no index.
Downgrade drops exactly what upgrade added.

The columns back optional acquisition attribution on the self-serve demo
tenant (see [demo-tenant.md](demo-tenant.md)). Omitting attribution leaves
issuance behavior unchanged.

## Compatibility release

Production boot refuses to start when the database's Alembic revision differs
from the packaged head in either direction. Applying 049 therefore retires
every image whose packaged head is `048_tenant_rls`: that image can no longer
restart against the upgraded database. The compatibility release is the
reviewed image that already packages `049_demo_key_attribution`, with demo
issuance still governed by `ENABLE_DEMO_TENANT` and with attribution left
NULL whenever the caller omits it. Ship that image and apply 049 together;
do not apply 049 under an image that does not package it.

This document records prerequisites, not permission to deploy or evidence of
an operational rollout. Staging and production state have not been
inspected. Before a separately authorized release, complete this record with
observed values and retained evidence. Placeholder values in the customer
manifest do not satisfy it.

| Required record | Status |
| --- | --- |
| Current database revision and current packaged head; private parity result | REQUIRED / UNVERIFIED |
| Current full build SHA, immutable image digest, deployment ID and worker IDs | REQUIRED / UNVERIFIED |
| Target full build SHA, immutable image digest, deployment ID and worker IDs | REQUIRED / UNVERIFIED |
| Target database revision and packaged head: `049_demo_key_attribution`; private parity result | REQUIRED / UNVERIFIED |
| Schema 048 (`048_tenant_rls`) applied first per its own rollout gate | REQUIRED / UNVERIFIED |
| Rehearsal: 048 → 049 upgrade on disposable PostgreSQL, legacy `api_keys` rows keep NULL attribution | REQUIRED / UNVERIFIED |

1. Verify the actual database revision and the serving image's packaged
   schema. Schema 049 requires 048; its rollout gate in
   [schema-048-rollout.md](schema-048-rollout.md) requires separate review.
   Rehearse 048 → 049 on fresh disposable PostgreSQL and confirm existing
   keys read back with NULL attribution on all six columns.
2. Use the canonical immutable exact-SHA release path in
   [deploy-railway.md](deploy-railway.md). Apply 049 through the reviewed
   migration entrypoint, then verify private schema parity, the baked build
   SHA, worker identity, runtime posture, health and logs. The serving image
   after this step must package `049_demo_key_attribution`.
3. Keep `ENABLE_DEMO_TENANT` at its pre-release value through the schema
   release. Attribution is stored only when demo issuance is already enabled
   and the caller supplies fields; the column add itself does not turn
   issuance on.

## Rollback after activation

Alembic `downgrade` from 049 to 048 drops `utm_source`, `utm_medium`,
`utm_campaign`, `utm_content`, `utm_term`, and `referrer`. That is a
schema-only reversal, not an operational rollback procedure: any attribution
captured while 049 was active is lost, and a 048-packaged image cannot
restart against a 049 database because schema parity is enforced. Before any
downgrade rehearsal, confirm the columns are unused or expendable and use a
disposable database only. Never downgrade a database that still serves
traffic, and never stamp a revision to skip the downgrade.

The record remains REQUIRED / UNVERIFIED until the corresponding
operational checks are performed under separate authorization. Local
integration and tests do not establish current deployment parity or a
rehearsed operational procedure.
