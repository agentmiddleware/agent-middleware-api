"""Phase 4: production schema boot uses Alembic, not create_all."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings
from app.db.database import (
    REQUIRED_TRUST_TABLES,
    SchemaInitError,
    allows_metadata_create_all,
    close_db,
    get_engine,
    init_db,
    verify_required_schema,
)


@pytest.mark.parametrize(
    ("dialect", "environment", "expected"),
    [
        ("sqlite", "local", True),
        ("sqlite", "test", True),
        ("sqlite", "ci", True),
        ("sqlite", "production", False),
        ("sqlite", "staging", False),
        ("postgresql", "local", False),
        ("postgresql", "production", False),
        ("postgresql", "development", False),
    ],
)
def test_allows_metadata_create_all_policy(dialect, environment, expected):
    assert (
        allows_metadata_create_all(dialect_name=dialect, environment=environment)
        is expected
    )


@pytest.mark.asyncio
async def test_init_db_sqlite_non_prod_uses_create_all(tmp_path, monkeypatch):
    db_path = tmp_path / "ephemeral.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("ENVIRONMENT", "local")
    get_settings.cache_clear()
    await close_db()

    await init_db()

    engine = get_engine()
    assert engine is not None
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert "permits" in tables
    assert "receipts" in tables
    assert "idempotency_records" in tables
    # create_all does not create alembic_version
    assert "alembic_version" not in tables

    await close_db()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_init_db_production_like_fails_without_migrations(tmp_path, monkeypatch):
    db_path = tmp_path / "empty_prod.db"
    # Empty file / no tables → verify must fail; create_all must not run.
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENABLE_PROOF_SURFACES", "false")
    get_settings.cache_clear()
    await close_db()

    with pytest.raises(SchemaInitError, match="Required database tables missing"):
        await init_db()

    # Confirm create_all did not paper over the empty DB.
    engine = create_engine(f"sqlite:///{db_path}")
    assert inspect(engine).get_table_names() == []
    engine.dispose()

    await close_db()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_init_db_production_like_accepts_legacy_create_all_tables(
    tmp_path, monkeypatch
):
    """Trust tables without alembic_version must still pass verify (no surprise outage)."""
    db_path = tmp_path / "legacy_prod.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("ENVIRONMENT", "local")
    get_settings.cache_clear()
    await close_db()
    # Simulate historical create_all bootstrap under local, then flip to prod.
    await init_db()
    await close_db()

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENABLE_PROOF_SURFACES", "false")
    get_settings.cache_clear()

    sync = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(sync).get_table_names())
    sync.dispose()
    assert REQUIRED_TRUST_TABLES <= tables
    assert "alembic_version" not in tables

    await init_db()  # must not raise SchemaInitError
    await close_db()
    get_settings.cache_clear()


def test_init_db_production_like_ok_after_alembic(tmp_path, monkeypatch):
    """Alembic must run outside an active event loop (env.py uses asyncio.run)."""
    import asyncio

    db_path = tmp_path / "migrated_prod.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENABLE_PROOF_SURFACES", "false")
    get_settings.cache_clear()

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    async def _verify_boot() -> None:
        await close_db()
        await init_db()  # verify-only path; must not raise
        engine = get_engine()
        assert engine is not None
        await verify_required_schema(engine)
        await close_db()

    asyncio.run(_verify_boot())

    sync = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(sync).get_table_names())
    assert REQUIRED_TRUST_TABLES <= tables
    assert "alembic_version" in tables
    sync.dispose()
    get_settings.cache_clear()


def test_docker_entrypoint_fails_closed_without_database_url():
    script = Path("scripts/docker_entrypoint.sh")
    assert script.is_file()
    env = os.environ.copy()
    env["RUN_MIGRATIONS_ON_START"] = "true"
    env.pop("DATABASE_URL", None)
    # Avoid accidentally inheriting a local DATABASE_URL
    result = subprocess.run(
        ["sh", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert "DATABASE_URL is empty" in result.stderr
    assert "refusing to start" in result.stderr


def test_alembic_upgrade_creates_trust_tables(tmp_path, monkeypatch):
    """Empty DB + alembic upgrade head yields permit/receipt/idempotency tables."""
    db_path = tmp_path / "trust_mig.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(sync_url)
    tables = set(inspect(engine).get_table_names())
    assert REQUIRED_TRUST_TABLES <= tables
    # Spot-check a trust column that migrations (not create_all) must own.
    permit_cols = {c["name"] for c in inspect(engine).get_columns("permits")}
    assert "permit_id" in permit_cols
    assert "spent_credits" in permit_cols
    engine.dispose()
