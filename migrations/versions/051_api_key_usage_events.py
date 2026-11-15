"""Store per-key API call facts and expose daily aggregates.

Revision ID: 051_api_key_usage_events
Revises: 050_demo_key_first_used

The event rows contain route templates only, never request payloads, raw URLs,
headers, client addresses, or credentials. Timestamps are naive UTC.
"""

from alembic import op
import sqlalchemy as sa

from app.core.config import get_settings
from app.db.api_key_usage_view import CREATE_API_KEY_USAGE_DAILY_VIEW_SQL

revision: str = "051_api_key_usage_events"
down_revision: str = "050_demo_key_first_used"
branch_labels = None
depends_on = None

_RLS_POLICY = "api_key_usage_events_admin_only"
_BYPASS = "current_setting('app.rls_bypass', true) = 'on'"


def upgrade() -> None:
    op.create_table(
        "api_key_usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("key_id", sa.String(length=50), nullable=False),
        sa.Column("tenant", sa.String(length=32), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_api_key_usage_events_key_created",
        "api_key_usage_events",
        ["key_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"CREATE POLICY {_RLS_POLICY} ON api_key_usage_events "
            f"AS PERMISSIVE FOR ALL USING ({_BYPASS}) WITH CHECK ({_BYPASS})"
        )
        if get_settings().TENANT_RLS_MODE == "enforce":
            op.execute("ALTER TABLE api_key_usage_events ENABLE ROW LEVEL SECURITY")
            op.execute("ALTER TABLE api_key_usage_events FORCE ROW LEVEL SECURITY")

    op.execute(CREATE_API_KEY_USAGE_DAILY_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS api_key_usage_daily")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {_RLS_POLICY} ON api_key_usage_events")
    op.drop_index(
        "ix_api_key_usage_events_key_created", table_name="api_key_usage_events"
    )
    op.drop_table("api_key_usage_events")
