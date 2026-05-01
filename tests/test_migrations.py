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
    assert {"api_keys", "key_rotation_logs", "kyc_verifications", "service_registry"} <= tables

    wallet_columns = {col["name"] for col in inspector.get_columns("wallets")}
    assert {
        "child_agent_id",
        "max_spend",
        "task_description",
        "ttl_seconds",
        "kyc_status",
        "kyc_verified_at",
    } <= wallet_columns

    engine.dispose()
    os.remove(db_path)
