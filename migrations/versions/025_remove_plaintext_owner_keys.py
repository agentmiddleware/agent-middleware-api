"""Remove plaintext API-key ownership columns.

Revision ID: 025_remove_plaintext_owner_keys
Revises: 024_human_approval_hardening
Create Date: 2026-08-05

Wallet and service ownership is represented by wallet identifiers and the
hashed API-key registry. The legacy owner_key columns duplicated live API
credentials in plaintext and were not required by the supported auth path.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_remove_plaintext_owner_keys"
down_revision: Union[str, None] = "024_human_approval_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove legacy plaintext API credentials from the active schema."""
    op.drop_index("ix_service_registry_owner_key", table_name="service_registry")
    op.drop_column("service_registry", "owner_key")
    op.drop_index("ix_wallets_owner_key", table_name="wallets")
    op.drop_column("wallets", "owner_key")


def downgrade() -> None:
    """Restore only the legacy shape; removed credentials are not reconstructed."""
    op.add_column(
        "wallets",
        sa.Column(
            "owner_key",
            sa.String(255),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index("ix_wallets_owner_key", "wallets", ["owner_key"])
    op.add_column(
        "service_registry",
        sa.Column(
            "owner_key",
            sa.String(255),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        "ix_service_registry_owner_key",
        "service_registry",
        ["owner_key"],
    )
