"""Migration coverage for production schema drift."""

import asyncio
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_auth_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", async_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    asyncio.set_event_loop(asyncio.new_event_loop())

    engine = create_engine(sync_url)
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert {
        "api_keys",
        "key_rotation_logs",
        "kyc_verifications",
        "service_registry",
        "signing_keys",
        "permits",
        "receipts",
        "idempotency_records",
        "human_approvals",
    } <= tables

    permit_columns = {col["name"] for col in inspector.get_columns("permits")}
    assert "requires_human_approval" in permit_columns
    receipt_columns = {col["name"] for col in inspector.get_columns("receipts")}
    assert "approval_id" in receipt_columns

    wallet_columns = {col["name"] for col in inspector.get_columns("wallets")}
    assert {
        "child_agent_id",
        "max_spend",
        "task_description",
        "ttl_seconds",
        "kyc_status",
        "kyc_verified_at",
    } <= wallet_columns

    audit_columns = {
        col["name"] for col in inspector.get_columns("control_plane_audit_events")
    }
    assert {
        "payload_hash",
        "previous_hash",
        "chain_hash",
        "signature",
        "signature_key_id",
    } <= audit_columns

    engine.dispose()
    os.remove(db_path)


def test_024_repairs_sqlite_boolean_backfill(tmp_path, monkeypatch):
    """Reproduce and verify the fix for the 023 SQLite boolean-default bug.

    023 added permits.requires_human_approval with server_default='false', which
    SQLite stores as the text 'false' and reads back through SQLAlchemy's
    non-native Boolean as True — silently flipping every pre-existing permit and
    breaking its signature. 024 must normalize those rows back to False.
    """
    from sqlalchemy import Boolean, Column, MetaData, String, Table, select, text

    db_path = tmp_path / "repair.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    config = Config("alembic.ini")

    # Upgrade only through 023, then simulate a pre-existing permit that 023's
    # ALTER backfilled with the text 'false'.
    command.upgrade(config, "023_human_approval_gate")
    asyncio.set_event_loop(asyncio.new_event_loop())
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        # Reproduce the 023 backfill: requires_human_approval = text 'false'.
        # Fill every NOT-NULL permit column; FK enforcement is off on this raw
        # engine so wallet/key references need not exist.
        conn.execute(
            text(
                "INSERT INTO permits (permit_id, issuer_wallet_id, "
                "subject_wallet_id, scopes_json, allowed_tools_json, max_credits, "
                "expires_at, nonce, status, requires_human_approval, signature, "
                "key_id, issued_at) VALUES ('p-legacy', 'w', 'w', '[]', '[]', 10, "
                "'2999-01-01 00:00:00', 'n', 'active', 'false', 'sig', 'k', "
                "'2026-01-01 00:00:00')"
            )
        )

    md = MetaData()
    permits = Table(
        "permits",
        md,
        Column("permit_id", String, primary_key=True),
        Column("requires_human_approval", Boolean),
    )
    # Before 024: the text 'false' reads back as True (the bug).
    with engine.connect() as conn:
        buggy = conn.execute(
            select(permits.c.requires_human_approval).where(
                permits.c.permit_id == "p-legacy"
            )
        ).scalar_one()
    assert buggy is True, "precondition: 023 leaves a truthy text value on SQLite"

    # 024 repairs it.
    command.upgrade(config, "024_human_approval_hardening")
    with engine.connect() as conn:
        fixed = conn.execute(
            select(permits.c.requires_human_approval).where(
                permits.c.permit_id == "p-legacy"
            )
        ).scalar_one()
    assert fixed is False, "024 must normalize the backfilled text 'false' to False"

    # 024's other change: the request_hash binding column exists.
    approval_columns = {
        col["name"] for col in inspect(engine).get_columns("human_approvals")
    }
    assert "request_hash" in approval_columns
    engine.dispose()
