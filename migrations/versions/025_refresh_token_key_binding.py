"""Bind refresh tokens to the API key that minted them.

A refresh token is derived authority: it exists only because a specific API key
was presented at POST /v1/auth/token. Without recording which key, revocation
can only be checked at wallet granularity, which is too coarse in the two cases
that matter most:

  * a wallet holding several keys — revoking the compromised one leaves a token
    minted from it renewable, because a sibling key is still active;
  * auto_rotate_on_suspicious_activity, which revokes the suspect key *and*
    issues a replacement, so the wallet is never keyless and the attacker's
    token survives the very rotation meant to contain it.

``key_id`` is nullable so historical rows remain representable, but the upgrade
revokes every unbound token. There is no reliable way to infer which API key
minted an existing row, and allowing one to rotate would let a token derived
from a revoked key survive whenever the wallet still has a sibling key. The
application also rejects NULL bindings so restored or partially migrated data
fails closed.

Deliberately no foreign key to ``api_keys``: this is a soft historical
reference to the minting key. A revoked key stays in the table (revocation is a
status change, not a delete), and the binding must survive even if a key row is
ever removed, since "the key this came from is gone" must fail closed rather
than error.

Revision ID: 025_refresh_token_key_binding
Revises: 024_human_approval_hardening
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "025_refresh_token_key_binding"
down_revision: Union[str, None] = "024_human_approval_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("key_id", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_refresh_tokens_key_id",
        "refresh_tokens",
        ["key_id"],
    )
    op.execute(
        sa.text(
            "UPDATE refresh_tokens SET revoked = :revoked WHERE key_id IS NULL"
        ).bindparams(revoked=True)
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_key_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "key_id")
