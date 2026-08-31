"""Mark remote attempts that reserved a permit call slot.

Existing attempts were prepared before the remote path incremented
``tool_call_counts_json``. They are backfilled false so compensation never
decrements a newer invocation's slot on their behalf.

Revision ID: 038_dispatch_call_slot_marker
Revises: 037_merge_trust_heads
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "038_dispatch_call_slot_marker"
down_revision: Union[str, None] = "037_merge_trust_heads"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_dispatch_attempts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "call_slot_reserved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_dispatch_attempts") as batch_op:
        batch_op.drop_column("call_slot_reserved")
