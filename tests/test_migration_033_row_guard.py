"""The 033 table drop must refuse to delete customer data.

Migration 033 drops optimizer_telemetry on the claim that nothing ever wrote
to it. If that claim is wrong for a given database, the upgrade must abort
before dropping anything instead of silently deleting rows.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REVISION_032 = "032_receipt_reason_code"
REVISION_033 = "033_drop_optimizer_telemetry"


def migrate(url, revision):
    env = {**os.environ, "DATABASE_URL": url}
    env.pop("ACTION_MIGRATION_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO_ROOT,
    )


def seed_telemetry_row(path):
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO optimizer_telemetry "
            "(ts, wallet_id, agent_id, endpoint) "
            "VALUES ('2026-01-01 00:00:00', 'w', 'agent', '/mcp')"
        )


def test_033_refuses_to_drop_a_table_that_holds_rows(tmp_path):
    path = tmp_path / "guard.sqlite"
    url = f"sqlite+aiosqlite:///{path}"
    result = migrate(url, REVISION_032)
    assert result.returncode == 0, result.stderr
    seed_telemetry_row(path)

    result = migrate(url, REVISION_033)
    assert result.returncode != 0, "033 deleted rows without complaint"
    assert "optimizer_telemetry" in result.stderr

    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM optimizer_telemetry").fetchone() == (1,)
        assert (
            db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == REVISION_032
        )


def test_033_still_drops_an_empty_table(tmp_path):
    path = tmp_path / "empty.sqlite"
    url = f"sqlite+aiosqlite:///{path}"
    result = migrate(url, REVISION_032)
    assert result.returncode == 0, result.stderr

    result = migrate(url, REVISION_033)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "optimizer_telemetry" not in tables
        assert (
            db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == REVISION_033
        )
