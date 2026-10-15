"""Add provider-status reconciliation columns to governed MCP dispatch attempts.

Additive and nullable (the probe counter defaults to zero). Existing
``delivery_uncertain`` rows upgrade to an unresolved reconcile status, which
is exactly their meaning today: parked for manual review. No data update or
backfill is performed, and ``state`` is never touched.

Revision ID: 047_dispatch_reconcile_lease
Revises: 046_demo_tenant_key_allowlist
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "047_dispatch_reconcile_lease"
down_revision: Union[str, None] = "046_demo_tenant_key_allowlist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_dispatch_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("reconcile_status", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reconcile_lease_owner", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reconcile_lease_expires_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reconcile_next_probe_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "reconcile_probe_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("reconciled_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_mcp_dispatch_attempts_reconcile_status", ["reconcile_status"]
        )
        batch_op.create_index(
            "ix_mcp_dispatch_attempts_reconcile_lease_expires_at",
            ["reconcile_lease_expires_at"],
        )
        batch_op.create_index(
            "ix_mcp_dispatch_attempts_reconcile_next_probe_at",
            ["reconcile_next_probe_at"],
        )


def downgrade() -> None:
    # Any non-NULL status is a durable provider decision. A refunded row's
    # refund and budget release outlive the column, and 046 accounting counts
    # every delivery_uncertain receipt as consumed, so a budget rebuild would
    # re-charge the released spend; a pending row may be half applied; and a
    # re-upgrade would re-probe every erased decision. Refuse rather than
    # silently drop any of them.
    bind = op.get_bind()
    decided = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM mcp_dispatch_attempts "
            "WHERE reconcile_status IS NOT NULL"
        )
    ).scalar_one()
    if decided:
        raise RuntimeError(
            f"047 downgrade refused: {decided} dispatch attempt(s) carry a "
            "reconcile_status decision that 046 cannot represent"
        )
    with op.batch_alter_table("mcp_dispatch_attempts") as batch_op:
        batch_op.drop_index("ix_mcp_dispatch_attempts_reconcile_next_probe_at")
        batch_op.drop_index("ix_mcp_dispatch_attempts_reconcile_lease_expires_at")
        batch_op.drop_index("ix_mcp_dispatch_attempts_reconcile_status")
        batch_op.drop_column("reconciled_at")
        batch_op.drop_column("reconcile_probe_count")
        batch_op.drop_column("reconcile_next_probe_at")
        batch_op.drop_column("reconcile_lease_expires_at")
        batch_op.drop_column("reconcile_lease_owner")
        batch_op.drop_column("reconcile_status")
