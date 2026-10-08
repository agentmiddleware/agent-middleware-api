"""Add per-key tool allowlist and demo-tenant labels.

Revision ID: 043_demo_tenant_key_allowlist
Revises: 042_permit_action_binding
"""

from alembic import op
import sqlalchemy as sa

revision: str = "043_demo_tenant_key_allowlist"
down_revision: str = "042_permit_action_binding"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.add_column(sa.Column("allowed_tools_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tenant", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_api_keys_tenant", ["tenant"])
    with op.batch_alter_table("wallets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tenant", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_wallets_tenant", ["tenant"])


def downgrade():
    with op.batch_alter_table("wallets", schema=None) as batch_op:
        batch_op.drop_index("ix_wallets_tenant")
        batch_op.drop_column("tenant")
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index("ix_api_keys_tenant")
        batch_op.drop_column("tenant")
        batch_op.drop_column("allowed_tools_json")
