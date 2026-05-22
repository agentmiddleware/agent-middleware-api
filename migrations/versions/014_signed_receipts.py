"""Signed receipt chain columns on wallets and ledger_entries.

Revision ID: 014_signed_receipts
Revises: 013_optimizer_telemetry
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014_signed_receipts"
down_revision: Union[str, None] = "013_optimizer_telemetry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Receipt chain head on the wallet.
    op.add_column(
        "wallets",
        sa.Column("receipt_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "wallets",
        sa.Column("last_receipt_hash", sa.String(length=64), nullable=True),
    )

    # Per-entry receipt fields. Nullable so pre-existing rows remain valid.
    op.add_column("ledger_entries", sa.Column("chain_seq", sa.Integer(), nullable=True))
    op.add_column(
        "ledger_entries", sa.Column("prev_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "ledger_entries", sa.Column("entry_hash", sa.String(length=64), nullable=True)
    )
    op.add_column("ledger_entries", sa.Column("signature", sa.Text(), nullable=True))
    op.add_column(
        "ledger_entries", sa.Column("receipt_alg", sa.String(length=20), nullable=True)
    )
    op.create_index("ix_ledger_entries_entry_hash", "ledger_entries", ["entry_hash"])


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_entry_hash", table_name="ledger_entries")
    for col in ("receipt_alg", "signature", "entry_hash", "prev_hash", "chain_seq"):
        op.drop_column("ledger_entries", col)
    op.drop_column("wallets", "last_receipt_hash")
    op.drop_column("wallets", "receipt_seq")
