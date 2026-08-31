"""Add a non-reacquirable claim to governed MCP dispatch attempts.

The nullable shape preserves historical rows. A historical ``dispatched`` row
with no claim is treated as already claimed and therefore cannot be retried.

This release also separates the human decision deadline from the durable,
single-use approved authority. All pending or approved rows created under the
former worker-clock/execute-before-expiry contract are retired before new
workers can observe or consume them; future approvals use database-authored
deadlines and decision timestamps, then remain durable until consumed.

Revision ID: 033_mcp_dispatch_claim_fence
Revises: 032_receipt_reason_code
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "033_mcp_dispatch_claim_fence"
down_revision: Union[str, None] = "032_receipt_reason_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    approvals = sa.table(
        "human_approvals",
        sa.column("status", sa.String(length=16)),
        sa.column("reason", sa.Text()),
    )
    op.execute(
        approvals.update()
        .where(approvals.c.status.in_(["pending", "approved"]))
        .values(
            status="expired",
            reason="approval_protocol_upgrade",
        )
    )
    with op.batch_alter_table("mcp_dispatch_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("dispatch_claim_hash", sa.String(length=64), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_dispatch_attempts") as batch_op:
        batch_op.drop_column("dispatch_claim_hash")
    # Intentionally do not revive approvals retired during upgrade. Restoring
    # an elapsed authorization would weaken the pre-upgrade security posture.
