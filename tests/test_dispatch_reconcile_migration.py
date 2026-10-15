"""Migration 047: additive reconcile-lease columns on dispatch attempts."""

import logging

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.db.database import REQUIRED_TRUST_COLUMNS
from app.db.models import McpDispatchAttemptModel

RECONCILE_COLUMNS = {
    "reconcile_status",
    "reconcile_lease_owner",
    "reconcile_lease_expires_at",
    "reconcile_next_probe_at",
    "reconcile_probe_count",
    "reconciled_at",
}


def test_model_and_boot_check_cover_reconcile_columns():
    table = McpDispatchAttemptModel.__table__
    assert RECONCILE_COLUMNS <= set(table.c.keys())
    assert table.c.reconcile_status.type.length == 32
    assert table.c.reconcile_lease_owner.type.length == 64
    assert RECONCILE_COLUMNS <= REQUIRED_TRUST_COLUMNS["mcp_dispatch_attempts"]


def test_047_is_the_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["047_dispatch_reconcile_lease"]


def test_reconcile_migration_preserves_parked_rows_and_guards_downgrade(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "dispatch-reconcile-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    sync_url = f"sqlite:///{db_path}"
    config = Config("alembic.ini")
    logging.getLogger("tests.dispatch_reconcile_migration").disabled = False

    command.upgrade(config, "046_demo_tenant_key_allowlist")
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO mcp_dispatch_attempts (
                    attempt_id, idempotency_record_id, wallet_id, permit_id,
                    public_tool_id, upstream_tool_name, upstream_origin,
                    request_hash, credits_authorized, credits_charged, state
                ) VALUES (
                    'dsp-legacy-parked', 'idm-legacy-parked', 'agt-legacy',
                    'permit-legacy', 'partner.legacy', 'partner_legacy',
                    'https://partner.example', :request_hash,
                    1, 1, 'delivery_uncertain'
                )
                """
            ),
            {"request_hash": "a" * 64},
        )
    engine.dispose()

    command.upgrade(config, "047_dispatch_reconcile_lease")
    engine = create_engine(sync_url)
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("mcp_dispatch_attempts")
    }
    assert RECONCILE_COLUMNS <= set(columns)
    assert columns["reconcile_probe_count"]["nullable"] is False
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT state, reconcile_status, reconcile_probe_count, "
                "reconcile_lease_owner FROM mcp_dispatch_attempts "
                "WHERE attempt_id = 'dsp-legacy-parked'"
            )
        ).one()
        # Parked rows upgrade to "unresolved" -- manual review, as before.
        assert tuple(row) == ("delivery_uncertain", None, 0, None)

    engine.dispose()

    # No recorded decision may be silently dropped: a completed refund would
    # be re-charged by 046 budget accounting, a pending one is half applied.
    for status in (
        "not_executed_refund_pending",
        "not_executed_refunded",
        "not_executed_review",
        "executed",
    ):
        engine = create_engine(sync_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE mcp_dispatch_attempts SET reconcile_status = :status "
                    "WHERE attempt_id = 'dsp-legacy-parked'"
                ),
                {"status": status},
            )
        engine.dispose()
        with pytest.raises(RuntimeError, match="047 downgrade refused"):
            command.downgrade(config, "046_demo_tenant_key_allowlist")

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE mcp_dispatch_attempts SET reconcile_status = NULL "
                "WHERE attempt_id = 'dsp-legacy-parked'"
            )
        )
    engine.dispose()

    # Unresolved rows carry nothing 046 cannot represent.
    command.downgrade(config, "046_demo_tenant_key_allowlist")
    engine = create_engine(sync_url)
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("mcp_dispatch_attempts")
    }
    assert not (RECONCILE_COLUMNS & columns)
    with engine.begin() as connection:
        state = connection.execute(
            text(
                "SELECT state FROM mcp_dispatch_attempts "
                "WHERE attempt_id = 'dsp-legacy-parked'"
            )
        ).scalar_one()
        assert state == "delivery_uncertain"
    engine.dispose()
