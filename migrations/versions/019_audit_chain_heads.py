"""Per-wallet audit chain head pointer.

Adds the `audit_chain_heads` table. Each row is locked FOR UPDATE during an
audit append so concurrent same-wallet writers serialize and cannot fork the
hash chain.

Revision ID: 019_audit_chain_heads
Revises: 018_permit_updated_at
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "019_audit_chain_heads"
down_revision: Union[str, None] = "018_permit_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_heads",
        sa.Column("wallet_key", sa.String(length=64), primary_key=True),
        sa.Column("last_chain_hash", sa.String(length=64), nullable=True),
        sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_chain_heads")
