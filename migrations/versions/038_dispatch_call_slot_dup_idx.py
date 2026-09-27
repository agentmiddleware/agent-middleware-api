"""add dispatch call slot and duplicate detection index

Revision ID: 038
Revises: 037
Create Date: 2026-09-27

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '038_dispatch_call_slot_dup_idx'
down_revision: str = '037_mcp_dispatch_claim_hash'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add call_slot_reserved column and duplicate detection index.
    
    The call_slot_reserved column tracks whether a dispatch attempt holds a
    per-tool call slot from the permit's max_calls_per_tool cap. The slot is
    reserved atomically with the budget at preparation time and released only
    when the attempt is compensated before dispatch.
    
    The (permit_id, public_tool_id, request_hash, created_at) index enables
    cross-key repeat detection: when a new idempotency key arrives with the
    same request hash as an active or succeeded attempt under the same permit
    and tool, it can be detected and refused as a duplicate.
    """
    # Add call_slot_reserved column
    op.add_column(
        'mcp_dispatch_attempts',
        sa.Column('call_slot_reserved', sa.Boolean(), nullable=False, server_default='0')
    )
    
    # Create index for duplicate detection.
    # Use CONCURRENTLY on Postgres to avoid blocking writes during index build.
    # SQLite doesn't support CONCURRENTLY, so check the connection type.
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        # Postgres: use CONCURRENTLY in an autocommit block with if-not-exists guard
        with op.get_context().autocommit_block():
            # Check if index already exists to make this idempotent
            index_exists = connection.execute(
                sa.text(
                    "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_mcp_dispatch_attempts_duplicate_detection'"
                )
            ).scalar()
            if not index_exists:
                connection.execute(
                    sa.text(
                        "CREATE INDEX CONCURRENTLY ix_mcp_dispatch_attempts_duplicate_detection "
                        "ON mcp_dispatch_attempts (permit_id, public_tool_id, request_hash, created_at)"
                    )
                )
    else:
        # SQLite: regular index creation
        op.create_index(
            'ix_mcp_dispatch_attempts_duplicate_detection',
            'mcp_dispatch_attempts',
            ['permit_id', 'public_tool_id', 'request_hash', 'created_at'],
            unique=False
        )


def downgrade() -> None:
    """Remove call_slot_reserved column and duplicate detection index."""
    op.drop_index(
        'ix_mcp_dispatch_attempts_duplicate_detection',
        table_name='mcp_dispatch_attempts'
    )
    
    with op.batch_alter_table('mcp_dispatch_attempts', schema=None) as batch_op:
        batch_op.drop_column('call_slot_reserved')
