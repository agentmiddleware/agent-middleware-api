"""Add durable local permit call reservations.

The table is intentionally additive and is not backfilled. Historical local
invocations do not persist enough pre-execution evidence to reconstruct a
reservation without assumptions; runtime compatibility continues to use their
receipts until they age out.

Revision ID: 034_permit_call_reservations
Revises: 033_mcp_dispatch_claim_fence
Create Date: 2026-08-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "034_permit_call_reservations"
down_revision: Union[str, None] = "033_mcp_dispatch_claim_fence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "permit_call_reservations",
        sa.Column(
            "idempotency_record_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("wallet_id", sa.String(length=50), nullable=False),
        sa.Column("permit_id", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "credits_authorized",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "call_slot_reserved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="reserved",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("execution_started_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "state IN ('reserved', 'consumed', 'released')",
            name="ck_permit_call_reservations_state",
        ),
        sa.CheckConstraint(
            "(state = 'reserved' AND execution_started_at IS NULL "
            "AND released_at IS NULL) OR "
            "(state = 'consumed' AND execution_started_at IS NOT NULL "
            "AND released_at IS NULL) OR "
            "(state = 'released' AND execution_started_at IS NULL "
            "AND released_at IS NOT NULL)",
            name="ck_permit_call_reservations_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_record_id"],
            ["idempotency_records.record_id"],
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.wallet_id"]),
        sa.ForeignKeyConstraint(["permit_id"], ["permits.permit_id"]),
        sa.PrimaryKeyConstraint("idempotency_record_id"),
    )
    op.create_index(
        "ix_permit_call_reservations_permit_tool_state",
        "permit_call_reservations",
        ["permit_id", "tool", "state"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_permit_call_reservations_permit_tool_state",
        table_name="permit_call_reservations",
    )
    op.drop_table("permit_call_reservations")
