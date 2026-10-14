# Tenant Row-Level Security (PostgreSQL)

Migration `047_tenant_rls` enables **and forces** PostgreSQL row-level security
on the wallet-scoped tables below. It is defense in depth under the
application-layer wallet checks (`AuthContext.require_wallet_access`), not a
replacement for them, and it is **not** a public multi-tenant isolation
guarantee (see [`SECURITY_LIMITATIONS.md`](../SECURITY_LIMITATIONS.md)). SQLite
is unaffected.

## What the policies say

Each table has one policy, `amw_tenant_isolation`, applied to every command
(`USING` for reads/updates/deletes, `WITH CHECK` for inserts/updates):

```sql
-- single-owner tables
(wallet_id = NULLIF(current_setting('app.current_wallet_id', true), ''))
  OR current_setting('app.rls_bypass', true) = 'on'

-- permits, permit_requests: visible to issuer and subject
(issuer_wallet_id  = NULLIF(current_setting('app.current_wallet_id', true), '')
 OR subject_wallet_id = NULLIF(current_setting('app.current_wallet_id', true), ''))
  OR current_setting('app.rls_bypass', true) = 'on'
```

* **Fail closed.** `current_setting(..., true)` is `NULL` when the setting was
  never set and `''` after a `SET LOCAL` ends. `NULLIF` folds both into `NULL`,
  and `NULL = x` admits nothing. A connection that sets neither setting reads
  and writes **no** rows in these tables.
* **Types.** Every wallet column is `character varying(50)`; the setting is
  `text`. They compare with built-in text equality: no cast, and the existing
  wallet indexes stay usable. (A future `uuid` column would need `::uuid` and
  a different empty-string guard; `tests/test_tenant_rls.py` pins the type.)
* **Bypass is exactly `'on'`.** Any other value (`true`, `1`) is not a bypass.

A second policy, `amw_delegated_issuer_read`, is **SELECT-only** and mirrors
the delegated-issuer branch of `authorize_receipt_access` (a permit's issuer may
read receipts filed under that permit's subject wallet):

| Table | Extra rows readable |
|---|---|
| `receipts` | Receipts whose permit has `issuer_wallet_id` = current wallet and `subject_wallet_id` = the receipt's wallet |
| `ledger_entries` | The entry a visible receipt names, and refunds correlated to it |
| `mcp_dispatch_attempts` | The attempt a visible receipt names |
| `idempotency_records` | The record a visible receipt names |

Those subqueries run through the receipts and permits policies themselves, so
they only follow links the caller can already see. They never admit a write
(`test_permit_issuer_reads_subject_receipt_and_its_ledger_only`). Each lookup
is covered by an existing index on `receipts`.

Covered tables (`app.db.tenant_rls.RLS_TABLES`, frozen in the migration):

`api_keys`, `billing_alerts`, `daily_balance_snapshots`, `human_approvals`,
`idempotency_records`, `key_rotation_logs`, `kyc_verifications`,
`ledger_entries`, `mcp_dispatch_attempts`, `permit_requests`, `permits`,
`policy_bundles`, `quotes`, `receipts`, `refresh_tokens`.

Not covered (deliberately, for now): `wallets` (the tenant root, read during
credential resolution and parent/child provisioning), `control_plane_audit_events`
and `audit_chain_heads` (carry wallet-less rows), the `insight_*` tables (own
authority model), `service_registry`, `signing_keys`, and proof-surface tables.

## Runtime modes: `TENANT_RLS_MODE`

| Mode | What the app does | Effect |
|---|---|---|
| `off` (default) | Opens every connection with `app.rls_bypass=on` as a startup parameter. | Policies are inert for the app, exactly as before the migration. Any *other* client connecting as a policy-bound role (psql, BI tools, a leaked runtime credential used outside the app) sees no rows. |
| `enforce` | Sets nothing at connection level. A session `after_begin` hook runs `SELECT set_config('app.current_wallet_id', :wallet, true), set_config('app.rls_bypass', :bypass, true)` inside each transaction. | Every transaction is limited to the authenticated wallet, or explicitly bypassed. |

`set_config(..., true)` is `SET LOCAL`: it is discarded at commit/rollback, so
a pooled connection never carries one request's wallet into the next checkout
(`test_set_local_scope_does_not_survive_commit`).

Where the scope comes from (`app/db/tenant_rls.py`):

* `get_auth_context` resolves the credential under an admin scope
  (`credential_resolution`: the key row is what names the wallet), then binds
  the request to the key's wallet, or to the bypass for bootstrap-admin keys
  (`bootstrap_admin`, already cross-wallet by design).
* The periodic maintenance task (dispatch reconciliation, budget repair, stuck
  idempotency records, upstream reconcile) binds `maintenance`.
* Anything else with no binding fails closed.

The binding is a `ContextVar` in the request's task, so it never crosses
requests.

### Startup posture check

On every boot against PostgreSQL the app reads `pg_roles` for `current_user`
and `pg_class` for the covered tables, and logs `phase="tenant_rls_posture"`.

* Runtime role is `SUPERUSER` or `BYPASSRLS` → warning
  `tenant_rls_role_bypasses_policies` in `off` mode; **boot refused** in
  `enforce` mode (superusers and BYPASSRLS roles skip every policy, `FORCE`
  included, so enforcement would be a claim the database does not make).
* A covered table without `ENABLE` + `FORCE` → boot refused in `enforce`.
* Runtime role owns the covered tables → warning only. `FORCE` keeps the owner
  bound, but an owner can `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY`.

## Database roles

Use two roles: an **owner** that runs migrations, and a **runtime** role the
API connects as. The runtime role must be `NOSUPERUSER NOBYPASSRLS` and must
**not** own the tables.

```sql
-- Owner: owns the schema and runs Alembic.
CREATE ROLE amw_owner LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE amw OWNER amw_owner;

-- Runtime: what DATABASE_URL uses.
CREATE ROLE amw_app LOGIN PASSWORD '...'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;

\c amw
GRANT ALL ON SCHEMA public TO amw_owner;
GRANT USAGE ON SCHEMA public TO amw_app;
-- Tables and sequences created by later migrations:
ALTER DEFAULT PRIVILEGES FOR ROLE amw_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO amw_app;
ALTER DEFAULT PRIVILEGES FOR ROLE amw_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO amw_app;
-- Tables that already exist (an upgraded database):
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO amw_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO amw_app;

-- Verify (both must be false):
SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'amw_app';
```

An existing deployment whose tables are owned by `postgres` can transfer them
(`ALTER TABLE ... OWNER TO amw_owner`) or keep `postgres` as the migration
role. Either way the runtime role must be a different, non-superuser role.

Container wiring: set `DATABASE_URL` to the runtime role and
`MIGRATION_DATABASE_URL` to the owner. `scripts/docker_entrypoint.sh` uses
`MIGRATION_DATABASE_URL` for `alembic upgrade head` only.

## Admin and cross-wallet paths

The explicit mechanism is `app.rls_bypass = 'on'`, set **locally to one
transaction**:

| Path | How it bypasses |
|---|---|
| Alembic migrations | `migrations/env.py` runs `set_config('app.rls_bypass', 'on', true)` inside the migration transaction. Needed because `FORCE` binds the owner too. |
| Credential resolution | `rls_admin_scope("credential_resolution")` around key/JWT lookup. |
| Bootstrap-admin requests | Scope `bootstrap_admin` bound after auth. |
| Maintenance loop | Scope `maintenance` bound at the start of the task. |
| Anonymous key minting | Route dependency `rls_admin_route(...)` on `POST /v1/dev-keys/self-provision` (local only) and `POST /v1/demo/keys`: they create rows for wallets that do not exist yet. |
| Provider webhooks | `rls_admin_route(...)` on `POST /v1/webhooks/stripe` and `/stripe/identity`: signature-verified, settle whichever wallet the event names. |
| JWT exchange (dormant) | Router-level `rls_admin_route("jwt_credential_exchange")` on `/v1/auth/*`: credential resolution, like the key lookup. |
| Two-wallet money movement | `_two_wallet_write` in `app/routers/billing.py` wraps sponsor→agent provisioning, parent→child provisioning and reclaim, and transfers, *after* the route's own wallet-access check. |
| Operator SQL / ad-hoc jobs | `BEGIN; SET LOCAL app.rls_bypass = 'on'; ...; COMMIT;` as the owner role, or a dedicated `BYPASSRLS` operator role that the API never uses. |

New code that is cross-wallet by design must wrap itself in
`rls_admin_scope("<reason>")`; the reason is required.

### What this does not defend against

The bypass setting is a session variable, so code that can already execute
arbitrary SQL as the runtime role can set it (or set
`app.current_wallet_id` to any wallet). The policies catch application queries
that forget a wallet filter, and contain clients that do not set the scope;
they are not a boundary against SQL injection or a compromised API process.
A `BYPASSRLS` operator role does not change that for the runtime role.

## Behavior differences under `enforce`

A cross-wallet reference is still refused, but the row is invisible to the
caller's transaction, so it is refused as **not found** rather than as a
binding mismatch. No row content is returned either way. Observed in the
enforce run:

| Surface | `off` | `enforce` |
|---|---|---|
| Governed invoke with another wallet's permit | `permit_wallet_mismatch` | `permit_not_found` |
| `POST /v1/permits/verify` for another wallet's permit | `403 permit_access_denied` | `200`, `reason=permit_not_found`, no permit body |
| Quote bound to another wallet | `quote_wallet_mismatch` | `quote_not_found` |
| `GET /v1/permit-requests/{id}` (and `/card`) from an unrelated wallet | `403` | `404` |

The first row has an audit cost: the denial audit event records
`permit_not_found`, so the specific confused-deputy signal ("someone presented
a real permit that is not theirs") is lost in `enforce`. Restoring it means
running those binding lookups before the caller's transaction begins under an
explicit scope; that is not done yet.

Unauthenticated routes that touch covered tables see nothing unless they bind
an admin scope. The ones found (key minting, webhooks, JWT exchange) do; the
local-only anonymous MCP endpoint (`/mcp/public`, refused in production) does
not, so receipt lookups through it return not found under `enforce`.

## Rollout

1. Deploy the migration with `TENANT_RLS_MODE=off` (the default). Behavior is
   unchanged; the startup log reports the role posture.
2. Create the runtime role, point `DATABASE_URL` at it, keep `off`. Confirm the
   log shows `superuser=false bypassrls=false`.
3. Set `TENANT_RLS_MODE=enforce`. Boot refuses if the role can bypass.
4. Roll back by setting `off` (no migration needed). `alembic downgrade
   046_demo_tenant_key_allowlist` drops the policies entirely.

## Evidence

* `tests/test_tenant_rls.py` — unit tests everywhere; with
  `TEST_RLS_POSTGRES_ADMIN_URL` it creates owner + runtime roles, migrates as
  the owner, and proves fail-closed reads/writes, wallet narrowing, `WITH
  CHECK`, issuer/subject permits, `SET LOCAL` not surviving commit, `FORCE`
  binding the owner, the session hook, off-mode bypass, the posture check, and
  downgrade/upgrade.
* CI (`postgres_trust` job) reruns the PostgreSQL trust-primitive suite as a
  `NOSUPERUSER NOBYPASSRLS` non-owner role under `TENANT_RLS_MODE=enforce`.
* Locally (2026-10-14, PostgreSQL 16) that suite plus 28 more governed-loop,
  billing, key, quote, permit-request, webhook, and reconciliation test files
  ran the same way. Everything passed except the denial-code differences in the
  table above (9 tests that assert the `off`-mode code). No hosted or
  production deployment has run `enforce`.
