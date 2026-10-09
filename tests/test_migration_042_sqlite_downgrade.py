"""Migration 042 downgrade must not open a nested transaction on SQLite.

The downgrade used to issue a raw ``BEGIN IMMEDIATE`` on SQLite. That opens
a driver-level transaction outside SQLAlchemy/alembic bookkeeping, so it
fails with "cannot start a transaction within a transaction" wherever a
transaction is already open. This test runs the real downgrade function with
a driver-level transaction already open: the old code raises, the fixed code
completes and drops the action binding columns.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

MIGRATION_FILE = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "042_permit_action_binding.py"
)

FIELDS = (
    "action_contract_version",
    "action_payload_hash",
    "action_schema_id",
    "action_schema_version",
    "action_public_tool_id",
    "action_upstream_binding_hash",
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_042_permit_action_binding", MIGRATION_FILE
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def column_names(connection, table):
    return [
        row[1] for row in connection.execute(sa.text(f"PRAGMA table_info({table})"))
    ]


def test_downgrade_inside_open_transaction(tmp_path):
    module = load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'downgrade.sqlite'}")
    with engine.connect() as connection:
        columns = ", ".join(f"{name} VARCHAR NULL" for name in FIELDS)
        connection.execute(
            sa.text(f"CREATE TABLE permits (id VARCHAR PRIMARY KEY, {columns})")
        )
        connection.execute(
            sa.text(f"CREATE TABLE receipts (id VARCHAR PRIMARY KEY, {columns})")
        )
        connection.execute(
            sa.text(
                "CREATE TABLE idempotency_records "
                "(record_id VARCHAR PRIMARY KEY, endpoint VARCHAR)"
            )
        )
        # Simulate the nested condition named in the audit: a transaction is
        # already open at the driver level when downgrade() runs.
        connection.connection.execute("BEGIN IMMEDIATE")
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.downgrade()
        connection.connection.execute("COMMIT")
        for table in ("permits", "receipts"):
            assert all(name not in column_names(connection, table) for name in FIELDS)
