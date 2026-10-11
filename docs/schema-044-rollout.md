# Schema 044: insight reporting authority

**Status: local synthetic verification only.** No production migration, issuer
configuration, principal, wallet grant, ownership epoch, endpoint, or export has
been authorized by this change. The production release gate is in
[the reporting authorization amendment](amw-insights-auth-amendment.md).

Revision `amw_insights_authority_20261010` follows
`042_permit_action_binding`. The filename reserves ordinal 044 while external
PR #766 proposes ordinal 043; the integration owner must reconcile the Alembic
graph if that PR merges. This revision adds:

- `insight_reporting_principals`: exact verified issuer and subject, a live
  interval, revocation, and an independent unknown-wallet-count permission.
- `insight_wallet_ownership_epochs`: an existing wallet, opaque owner boundary,
  half-open historical interval, and explicit completeness flag.
- `insight_reporting_wallet_grants`: exact principal, wallet, and epoch with a
  live interval distinct from a bounded historical evidence interval. A
  composite foreign key prevents grants from naming an epoch on another wallet.

The application reads these tables only. There is no grant issuance or
revocation route. Without an explicitly verified enterprise bearer, a live
principal and grant, and complete non-overlapping wallet history, authorization
denies. The current OIDC parser verifies the configured audience but does not
distinguish ID-token class; production setup must use a resource/API audience,
not an OIDC client ID. Grant and epoch population and revocation procedures
need separate approval before reporting can be enabled.
Ownership epochs represent certified history, but this local schema does not
prevent their UPDATE or DELETE. Production grant activation requires an
append-only certification process backed by database privileges or triggers
that prevent edits to certified epochs. It must also verify original ownership
provenance before any historical grant is issued.

## Synthetic PostgreSQL verification

Use only the disposable `amw_insights_auth_test` database on loopback port
`55489`:

```sh
DATABASE_URL=postgresql+asyncpg://sellers@127.0.0.1:55489/amw_insights_auth_test \
  .venv/bin/alembic upgrade head
AMW_INSIGHTS_TEST_DATABASE_URL=postgresql+asyncpg://sellers@127.0.0.1:55489/amw_insights_auth_test \
  .venv/bin/pytest tests/test_operation_insights_auth.py -q
```

The default SQLite suite explicitly skips PostgreSQL-only snapshot cases. A
production rollout still needs review of the migration graph, a backup and
rollback plan, issuer resource audience, least-privilege read role or replica,
historical ownership provenance, exact grant assignments and revocation,
append-only epoch enforcement, export access and retention, and deployed
revision parity.

## Rollback boundary

An older application image cannot restart against a database upgraded to this
head. Keep reporting and event capture disabled until a separate rollout is
approved. If rollout is stopped, preserve existing authority and evidence rows;
`downgrade()` refuses to drop nonempty authority tables. Reconcile the deployed
image and migration graph before any approved schema reversal.
