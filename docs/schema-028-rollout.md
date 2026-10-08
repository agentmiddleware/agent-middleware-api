# Schema 028: unbound refresh-token revocation and rollback boundary

Migration `028_revoke_unbound_refresh` revises `027_governed_mcp_identity`.
It is data-only and irreversible by design. Revision 025 added
`refresh_tokens.key_id` but left historical rows NULL, and the application
now fails closed on NULL bindings, because an unbound token could rotate
forever through a live sibling of a revoked key. This migration durably
revokes every historical row that cannot be attributed to a key.

## Buyer and operator impact

Applying 028 logs out every session whose refresh token predates key
binding. Those users must sign in again; there is no silent reissue. The
revocation cannot be undone by rolling back: the downgrade is an intentional
no-op, because the prior state cannot distinguish tokens that were already
revoked from tokens this migration revoked. Plan this migration as a
one-time forced re-login for old sessions, and announce it before a paid
pilot or production upgrade.

## Release

No compatibility release is needed: no column changes shape, and old and
new workers read the same `revoked` flag. Deploy an image whose packaged
head includes 028 through the canonical migration-on-start path so the
revocation runs once before traffic is served.

1. Confirm the production database is at `027_governed_mcp_identity`. An
   earlier revision needs its own migration review first.
2. Announce the forced re-login window to affected users before applying.
3. Apply 028, then verify that only rows with NULL `key_id` changed state
   and that currently bound sessions still refresh.

## Rollback after activation

Rolling the database stamp back to 027 restores no sessions: revoked stays
revoked, and the application still fails closed on NULL bindings. Recover
forward with an image whose packaged head is 028 or later. Do not run
`alembic downgrade` to 027 as a rollback; it moves only the stamp while the
data stays revoked, which misrepresents the database state to the next
operator.
