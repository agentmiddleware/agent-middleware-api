# Schema 043: demo-tenant labels and per-key tool allowlist

Migration `043_demo_tenant_key_allowlist` revises
`042_permit_action_binding`. It adds two nullable columns to `api_keys`
(`allowed_tools_json` TEXT, `tenant` VARCHAR(32)) and one nullable column to
`wallets` (`tenant` VARCHAR(32)), plus an index on each `tenant` column.
Existing rows are untouched: every pre-existing key keeps
`allowed_tools_json = NULL` (unrestricted) and every pre-existing wallet
keeps `tenant = NULL` (normal), so behavior with `ENABLE_DEMO_TENANT=false`
and no allowlists set is unchanged. Downgrade drops exactly what upgrade
added; it is never run in production.

The columns back the self-serve demo tenant (`POST /v1/demo/keys`, see
[docs/demo-tenant.md](demo-tenant.md)): tenant is a property of the wallet,
inherited by child wallets and stamped onto keys at creation, and a key may
additionally carry a tool allowlist enforced at permit creation and at
invoke. No data migration, no default that rewrites rows, no change to the
042 action-binding columns or their authority-retention downgrade guard.

## Release prerequisites and compatibility

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
| Target database revision and packaged head: `043_demo_tenant_key_allowlist`; private parity result | REQUIRED / UNVERIFIED |
| Rehearsal: 042 → 043 upgrade on disposable PostgreSQL, legacy rows keep NULL labels | REQUIRED / UNVERIFIED |
| `ENABLE_DEMO_TENANT` stays `false` until the separately authorized launch; issuance 404 verified | REQUIRED / UNVERIFIED |

1. Verify the actual database is at `042_permit_action_binding` and the
   serving image has matching packaged schema. Earlier revisions require
   their own review under their own rollout notes. Rehearse 042 → 043 on
   fresh disposable PostgreSQL and confirm existing keys and wallets read
   back with NULL allowlist/tenant labels.
2. Use the canonical immutable exact-SHA release path in
   [deploy-railway.md](deploy-railway.md). Apply 043 through the reviewed
   migration entrypoint, then verify private schema parity, the baked build
   SHA, worker identity, runtime posture, health and logs.
3. Keep `ENABLE_DEMO_TENANT=false` through the release. The demo issuance
   surface, demo keys, and demo wallets activate only under a separately
   authorized flag flip (which additionally requires `REDIS_URL` in
   production-like environments, enforced at boot).

## Rollback after activation

Alembic `downgrade` from 043 to 042 drops `api_keys.allowed_tools_json`,
`api_keys.tenant`, and `wallets.tenant` (with their indexes). That is a
schema-only reversal, not an operational rollback procedure: any demo keys,
demo wallets, or allowlisted keys created while 043 was active lose their
labels silently, and a 042-packaged image cannot restart against a 043
database because schema parity is enforced. Before any downgrade rehearsal,
revoke all demo keys (`POST /v1/demo/admin/revoke-all`), confirm no rows
carry tenant or allowlist labels, and use a disposable database only. Never
downgrade a database that still serves traffic, and never stamp a revision
to skip the downgrade.

The record remains REQUIRED / UNVERIFIED until the corresponding
operational checks are performed under separate authorization. Local
integration and tests do not establish current deployment parity or a
rehearsed operational procedure.
