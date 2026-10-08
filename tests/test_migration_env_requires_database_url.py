"""The migration runner must not silently fall back to SQLite in production.

When DATABASE_URL is unset, migrations/env.py falls back to a local SQLite
file. On a production-like deployment that masks a dropped variable: the
migration would run against a fresh local file while the real database sits
unmigrated. Production-like ENVIRONMENT values must fail loudly instead.
Local runs keep the file fallback so checkouts stay friction-free.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "001_initial"
FALLBACK_FILENAME = "agent_middleware.db"


def run_alembic(args, extra_env):
    env = {**os.environ, **extra_env}
    env.pop("DATABASE_URL", None)
    env.pop("ACTION_MIGRATION_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO_ROOT,
    )


def test_missing_database_url_fails_loudly_in_production():
    fallback = REPO_ROOT / FALLBACK_FILENAME
    assert not fallback.exists(), (
        f"pre-existing {FALLBACK_FILENAME} would confuse this test; "
        "remove it before running"
    )
    result = run_alembic(["upgrade", BASE_REVISION], {"ENVIRONMENT": "production"})
    try:
        assert result.returncode != 0, (
            "migrations ran without DATABASE_URL in production; "
            f"stdout={result.stdout[-500:]} stderr={result.stderr[-500:]}"
        )
        assert "DATABASE_URL" in result.stderr
    finally:
        if fallback.exists():
            fallback.unlink()
    assert not fallback.exists(), "production run must not create a fallback file"


def test_missing_database_url_still_falls_back_locally():
    fallback = REPO_ROOT / FALLBACK_FILENAME
    assert not fallback.exists(), (
        f"pre-existing {FALLBACK_FILENAME} would confuse this test; "
        "remove it before running"
    )
    try:
        result = run_alembic(["upgrade", BASE_REVISION], {"ENVIRONMENT": "local"})
        assert result.returncode == 0, result.stderr
        assert fallback.exists()
    finally:
        if fallback.exists():
            fallback.unlink()
