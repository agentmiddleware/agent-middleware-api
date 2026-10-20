"""API key usage tracking: events table, daily aggregation view, admin endpoint.

Revision ID: 051_api_key_usage_events
Revises: 050_demo_key_first_used

Adds an append-only ``api_key_usage_events`` table to record per-call usage
metadata (no request bodies, IPs, or PII), a read-only view
``api_key_usage_daily`` that aggregates events per key per UTC day, and the
supporting infrastructure for an admin-only endpoint that surfaces the view.

Downgrade drops the view and the table.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "051_api_key_usage_events"
down_revision: str = "050_demo_key_first_used"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_key_usage_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=50), nullable=False),
        sa.Column("tenant", sa.String(length=32), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("route_template", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["api_keys.key_id"],
        ),
    )
    op.create_index(
        "ix_api_key_usage_events_key_id_created_at",
        "api_key_usage_events",
        ["key_id", "created_at"],
    )

    # Daily aggregation view
    op.execute(
        """
        CREATE VIEW api_key_usage_daily AS
        SELECT
            key_id,
            DATE(created_at) AS day,
            COUNT(*) AS calls,
            SUM(CASE WHEN status_code >= 400 AND status_code < 500 THEN 1 ELSE 0 END) AS count_4xx,
            SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS count_5xx,
            CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) AS INTEGER) AS p50_latency_ms,
            CAST(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS INTEGER) AS p95_latency_ms,
            MIN(created_at) AS first_call,
            MAX(created_at) AS last_call
        FROM api_key_usage_events
        GROUP BY key_id, DATE(created_at)
        """
        if op.get_bind().dialect.name == "postgresql"
        else """
        CREATE VIEW api_key_usage_daily AS
        SELECT
            key_id,
            DATE(created_at) AS day,
            COUNT(*) AS calls,
            SUM(CASE WHEN status_code >= 400 AND status_code < 500 THEN 1 ELSE 0 END) AS count_4xx,
            SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS count_5xx,
            (
                SELECT latency_ms
                FROM (
                    SELECT latency_ms,
                           ROW_NUMBER() OVER (ORDER BY latency_ms) as rn,
                           COUNT(*) OVER () as cnt
                    FROM api_key_usage_events e2
                    WHERE e2.key_id = e1.key_id AND DATE(e2.created_at) = DATE(e1.created_at)
                ) sub
                WHERE rn = (cnt + 1) / 2
            ) AS p50_latency_ms,
            (
                SELECT latency_ms
                FROM (
                    SELECT latency_ms,
                           ROW_NUMBER() OVER (ORDER BY latency_ms) as rn,
                           COUNT(*) OVER () as cnt
                    FROM api_key_usage_events e2
                    WHERE e2.key_id = e1.key_id AND DATE(e2.created_at) = DATE(e1.created_at)
                ) sub
                WHERE rn = CAST(cnt * 0.95 AS INTEGER)
            ) AS p95_latency_ms,
            MIN(created_at) AS first_call,
            MAX(created_at) AS last_call
        FROM api_key_usage_events e1
        GROUP BY key_id, DATE(created_at)
        """
    )


def downgrade():
    op.execute("DROP VIEW IF EXISTS api_key_usage_daily")
    op.drop_index("ix_api_key_usage_events_key_id_created_at", table_name="api_key_usage_events")
    op.drop_table("api_key_usage_events")
