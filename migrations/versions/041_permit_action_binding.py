"""Add nullable signed single-action binding fields.

Revision ID: 041_permit_action_binding
Revises: 040_permit_repeat_window
"""

from alembic import op
import sqlalchemy as sa

revision: str = "041_permit_action_binding"
down_revision: str = "040_permit_repeat_window"
branch_labels = None
depends_on = None

_FIELDS = (
    "action_contract_version",
    "action_payload_hash",
    "action_schema_id",
    "action_schema_version",
    "action_public_tool_id",
    "action_upstream_binding_hash",
)


def upgrade():
    for table in ("permits", "receipts"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            for name in _FIELDS:
                batch_op.add_column(
                    sa.Column(
                        name,
                        sa.Integer()
                        if name == "action_contract_version"
                        else sa.String(),
                        nullable=True,
                    )
                )


def downgrade():
    for table in ("receipts", "permits"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            for name in reversed(_FIELDS):
                batch_op.drop_column(name)
