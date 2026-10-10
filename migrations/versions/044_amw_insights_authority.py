"""Add explicit read-only reporting principals and wallet ownership epochs.

Revision ID: amw_insights_authority_20261010
Revises: 042_permit_action_binding

This revision is for local synthetic verification only until the separate
production reporting release gate is approved.
"""

from alembic import op
import sqlalchemy as sa


revision = "amw_insights_authority_20261010"
down_revision = "042_permit_action_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insight_reporting_principals",
        sa.Column("principal_id", sa.String(length=64), primary_key=True),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "allow_unknown_wallet_counts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint("issuer", "subject", name="uq_insight_principal_identity"),
        sa.CheckConstraint(
            "starts_at < expires_at", name="ck_insight_principal_liveness"
        ),
    )
    op.create_table(
        "insight_wallet_ownership_epochs",
        sa.Column("ownership_epoch_id", sa.String(length=128), primary_key=True),
        sa.Column("wallet_id", sa.String(length=50), nullable=False),
        sa.Column("owner_boundary_id", sa.String(length=128), nullable=False),
        sa.Column("evidence_from", sa.DateTime(), nullable=False),
        sa.Column("evidence_until", sa.DateTime(), nullable=False),
        sa.Column(
            "history_complete", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.wallet_id"]),
        sa.UniqueConstraint(
            "wallet_id", "ownership_epoch_id", name="uq_insight_epoch_wallet_id"
        ),
        sa.CheckConstraint(
            "evidence_from < evidence_until", name="ck_insight_epoch_range"
        ),
    )
    op.create_index(
        "ix_insight_wallet_ownership_epochs_wallet_id",
        "insight_wallet_ownership_epochs",
        ["wallet_id"],
    )
    op.create_table(
        "insight_reporting_wallet_grants",
        sa.Column("grant_id", sa.String(length=64), primary_key=True),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("wallet_id", sa.String(length=50), nullable=False),
        sa.Column("ownership_epoch_id", sa.String(length=128), nullable=False),
        sa.Column(
            "permission_kind",
            sa.String(length=32),
            nullable=False,
            server_default="wallet_evidence_read",
        ),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_from", sa.DateTime(), nullable=False),
        sa.Column("evidence_until", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["insight_reporting_principals.principal_id"]
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id", "ownership_epoch_id"],
            [
                "insight_wallet_ownership_epochs.wallet_id",
                "insight_wallet_ownership_epochs.ownership_epoch_id",
            ],
            name="fk_insight_grant_wallet_epoch",
        ),
        sa.UniqueConstraint(
            "principal_id",
            "wallet_id",
            "ownership_epoch_id",
            name="uq_insight_grant_principal_wallet_epoch",
        ),
        sa.CheckConstraint("starts_at < expires_at", name="ck_insight_grant_liveness"),
        sa.CheckConstraint(
            "evidence_from < evidence_until", name="ck_insight_grant_range"
        ),
    )
    op.create_index(
        "ix_insight_reporting_wallet_grants_principal_id",
        "insight_reporting_wallet_grants",
        ["principal_id"],
    )
    op.create_index(
        "ix_insight_reporting_wallet_grants_wallet_id",
        "insight_reporting_wallet_grants",
        ["wallet_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "insight_reporting_wallet_grants",
        "insight_wallet_ownership_epochs",
        "insight_reporting_principals",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("insight_reporting_authority_retained")
    op.drop_index(
        "ix_insight_reporting_wallet_grants_wallet_id",
        table_name="insight_reporting_wallet_grants",
    )
    op.drop_index(
        "ix_insight_reporting_wallet_grants_principal_id",
        table_name="insight_reporting_wallet_grants",
    )
    op.drop_table("insight_reporting_wallet_grants")
    op.drop_index(
        "ix_insight_wallet_ownership_epochs_wallet_id",
        table_name="insight_wallet_ownership_epochs",
    )
    op.drop_table("insight_wallet_ownership_epochs")
    op.drop_table("insight_reporting_principals")
