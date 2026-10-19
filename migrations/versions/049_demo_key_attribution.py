"""Store optional UTM and referrer attribution on demo API keys.

Revision ID: 049_demo_key_attribution
Revises: 048_tenant_rls

Nullable columns. Existing keys, including demo keys issued before this
migration, stay NULL. Only POST /v1/demo/keys writes them.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "049_demo_key_attribution"
down_revision: str = "048_tenant_rls"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("utm_source", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("utm_medium", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("utm_campaign", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("utm_content", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(sa.Column("utm_term", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("referrer", sa.String(length=512), nullable=True))


def downgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_column("referrer")
        batch_op.drop_column("utm_term")
        batch_op.drop_column("utm_content")
        batch_op.drop_column("utm_campaign")
        batch_op.drop_column("utm_medium")
        batch_op.drop_column("utm_source")
