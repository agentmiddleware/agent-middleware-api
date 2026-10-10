"""Create default-off, payload-free prospective operation event storage.

Revision ID: amw_insights_events_20261010
Revises: amw_insights_authority_20261010
"""

from alembic import op
import sqlalchemy as sa


revision: str = "amw_insights_events_20261010"
down_revision: str = "amw_insights_authority_20261010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_insight_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("attempt_id", sa.String(128), nullable=True),
        sa.Column("logical_operation_id", sa.String(128), nullable=True),
        sa.Column("wallet_id", sa.String(128), nullable=True),
        sa.Column("ownership_epoch_id", sa.String(128), nullable=True),
        sa.Column("original_operation_anchor_id", sa.String(128), nullable=True),
        sa.Column("request_disposition", sa.String(32), nullable=True),
        sa.Column("tool", sa.String(128), nullable=True),
        sa.Column("reason_code", sa.String(128), nullable=True),
        sa.Column("gateway_outcome", sa.String(16), nullable=True),
        sa.Column("effect_state", sa.String(20), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("duplicate_conflict_at", sa.DateTime(), nullable=True),
        sa.Column("classification_version", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(128), nullable=True),
        sa.Column("server_release", sa.String(128), nullable=True),
        sa.Column("deployment", sa.String(128), nullable=True),
        sa.Column("client_version", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_insight_events_wallet_time",
        "operation_insight_events",
        ["wallet_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_insight_events_request",
        "operation_insight_events",
        ["request_id", "event_id"],
    )
    op.create_index(
        "ix_operation_insight_events_occurred_at",
        "operation_insight_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("LOCK TABLE operation_insight_events IN ACCESS EXCLUSIVE MODE")
        )
    if connection.execute(
        sa.text("SELECT 1 FROM operation_insight_events LIMIT 1")
    ).first():
        raise RuntimeError("insight_events_retained: preserve prospective evidence")
    op.drop_index(
        "ix_operation_insight_events_occurred_at",
        table_name="operation_insight_events",
    )
    op.drop_index("ix_insight_events_request", table_name="operation_insight_events")
    op.drop_index(
        "ix_insight_events_wallet_time", table_name="operation_insight_events"
    )
    op.drop_table("operation_insight_events")
