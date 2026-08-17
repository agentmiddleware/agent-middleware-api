"""DATABASE_URL normalization and durable-state fail-closed behavior."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.core.db_urls import (
    as_asyncpg_url,
    as_sqlalchemy_url,
    is_postgres_url,
    sqlite_path_from_url,
)
from app.core.durable_state import (
    _TRACKED_SQLITE_CONNECTIONS,
    _release_tracked_sqlite_connections,
    DurableStateConfigError,
    DurableStateStore,
    reset_durable_state_for_tests,
)
from app.core.runtime_degradation import (
    get_runtime_degradation,
    reset_runtime_degradation,
)


def test_as_sqlalchemy_url_postgres_variants():
    assert as_sqlalchemy_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert as_sqlalchemy_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert (
        as_sqlalchemy_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql+asyncpg://u:p@h/db"
    )
    assert (
        as_sqlalchemy_url("sqlite+aiosqlite:///./x.db") == "sqlite+aiosqlite:///./x.db"
    )
    assert as_sqlalchemy_url("") == ""


def test_as_asyncpg_url_strips_driver():
    assert as_asyncpg_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert as_asyncpg_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"
    assert as_asyncpg_url("postgres://u:p@h/db") == "postgresql://u:p@h/db"


def test_uppercase_schemes_normalize_without_touching_credentials():
    """is_postgres_url accepts any case, so the converters must too.

    Only the scheme is lowercased — user, password, host, and path are
    case-sensitive and must survive verbatim.
    """
    upper = "POSTGRESQL://Us3R:PaSsW0rd@Host/DB"
    assert is_postgres_url(upper)
    assert as_asyncpg_url(upper) == "postgresql://Us3R:PaSsW0rd@Host/DB"
    assert as_sqlalchemy_url(upper) == "postgresql+asyncpg://Us3R:PaSsW0rd@Host/DB"
    assert as_asyncpg_url("POSTGRES://u:p@h/db") == "postgresql://u:p@h/db"


def test_url_helpers_are_idempotent():
    raw = "postgresql://u:p@h/db"
    sa = as_sqlalchemy_url(raw)
    assert as_sqlalchemy_url(sa) == sa
    assert as_asyncpg_url(as_asyncpg_url(sa)) == as_asyncpg_url(sa)
    assert as_asyncpg_url(sa) == raw


def test_suite_runs_on_memory_durable_state():
    """The suite's own durable-state posture, asserted rather than assumed.

    conftest sets STATE_BACKEND=memory. Without it, the SQLite DATABASE_URL the
    suite also sets would resolve to the SQLite backend and open an aiosqlite
    connection whose worker thread is not a daemon — an unclosed one blocks
    interpreter shutdown, so the suite passes and pytest never exits. This guard
    fails loudly if that line is ever dropped.
    """
    assert DurableStateStore()._resolve_backend() == "memory"


def test_is_postgres_url_rejects_non_postgres_backends():
    assert is_postgres_url("postgresql://u:p@h/db")
    assert is_postgres_url("postgres://u:p@h/db")
    assert is_postgres_url("postgresql+asyncpg://u:p@h/db")
    assert is_postgres_url("POSTGRESQL://u:p@h/db")
    assert not is_postgres_url("sqlite+aiosqlite:///./x.db")
    assert not is_postgres_url("")


def test_sqlite_path_from_url_extracts_aiosqlite_path():
    assert sqlite_path_from_url("sqlite+aiosqlite:///./x.db") == "./x.db"
    assert sqlite_path_from_url("sqlite+aiosqlite:////abs/x.db") == "/abs/x.db"
    assert sqlite_path_from_url("sqlite:///./x.db") == "./x.db"
    assert sqlite_path_from_url("postgresql://u:p@h/db") == ""
    assert sqlite_path_from_url("") == ""


def test_in_memory_sqlite_is_not_a_durable_path():
    """In-memory SQLite must never be offered as durable state.

    It is valid SQLite but keeps nothing across a restart, so accepting it
    would reintroduce the silent non-durability this helper prevents.
    """
    assert sqlite_path_from_url("sqlite:///:memory:") == ""
    assert sqlite_path_from_url("sqlite+aiosqlite:///:memory:") == ""
    assert sqlite_path_from_url("sqlite+aiosqlite://") == ""
    assert sqlite_path_from_url("sqlite+aiosqlite:///file::memory:?cache=shared") == ""
    assert sqlite_path_from_url("sqlite+aiosqlite:///file:x?mode=memory") == ""


def test_durable_filenames_containing_memory_text_are_kept():
    """``mode=memory`` counts only as a file: URI query parameter.

    A substring test would classify these durable paths as ephemeral and route
    their state to memory, losing it on restart.
    """
    assert sqlite_path_from_url("sqlite:///mode=memory.db") == "mode=memory.db"
    assert (
        sqlite_path_from_url("sqlite+aiosqlite:////var/data/mode=memory/app.db")
        == "/var/data/mode=memory/app.db"
    )


def test_auto_backend_does_not_select_in_memory_sqlite(monkeypatch):
    """An in-memory DATABASE_URL falls through rather than posing as durable."""
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("STATE_BACKEND", "auto")
    monkeypatch.setenv("SQLITE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    assert store._resolve_backend() == "memory"
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_auto_backend_uses_sqlite_for_a_sqlite_database_url(monkeypatch):
    """A SQLite DATABASE_URL must not route auto-resolution to asyncpg.

    Regression: auto-resolution treated any non-empty DATABASE_URL as postgres,
    so the standard local setting sent a sqlite DSN to asyncpg, logged a
    connection traceback, and silently degraded durable state to in-memory.
    """
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("STATE_BACKEND", "auto")
    monkeypatch.setenv("SQLITE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./local.db")
    monkeypatch.setenv("REDIS_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    assert store._resolve_backend() == "sqlite"
    assert store._sqlite_url == "./local.db"
    report = get_runtime_degradation()
    assert report["durable_state"]["fell_back_to_memory"] is False
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_auto_backend_still_uses_postgres_for_a_postgres_database_url(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("STATE_BACKEND", "auto")
    monkeypatch.setenv("SQLITE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    assert store._resolve_backend() == "postgres"
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_sqlite_without_url_falls_back_outside_production(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    assert store._resolve_backend() == "memory"
    report = get_runtime_degradation()
    assert report["durable_state"]["fell_back_to_memory"] is True
    assert report["durable_state"]["intended_backend"] == "sqlite"
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_sqlite_without_url_refuses_production_like(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    with pytest.raises(DurableStateConfigError, match="SQLITE_URL"):
        store._resolve_backend()
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


@pytest.mark.anyio
async def test_postgres_init_fail_closed_in_production(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://nobody:wrong@127.0.0.1:1/none"
    )
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    with pytest.raises(DurableStateConfigError, match="failed to initialize"):
        await store._ensure_ready()
    report = get_runtime_degradation()
    assert report["durable_state"]["fell_back_to_memory"] is True
    assert report["durable_state"]["intended_backend"] == "postgres"
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_memory_backend_forbidden_in_production(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("STATE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    with pytest.raises(DurableStateConfigError, match="memory is not allowed"):
        store._resolve_backend()
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_postgres_missing_url_refuses_production_like(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SQLITE_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    with pytest.raises(DurableStateConfigError, match="DATABASE_URL"):
        store._resolve_backend()
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


def test_auto_without_urls_refuses_production_like(monkeypatch):
    reset_runtime_degradation()
    reset_durable_state_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("STATE_BACKEND", "auto")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SQLITE_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    store = DurableStateStore()
    with pytest.raises(DurableStateConfigError, match="require DATABASE_URL"):
        store._resolve_backend()
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    reset_runtime_degradation()


# --- shutdown backstop for the aiosqlite worker thread ---------------------
# aiosqlite.Connection composes a worker Thread with no daemon=True, and
# interpreter shutdown joins non-daemon threads. A connection nobody closes
# therefore hangs the process at exit with no traceback. close() is the real
# cleanup path; these cover the backstop for consumers that never reach it.

# Opens the SQLite backend and exits WITHOUT calling close_durable_state().
# Without the backstop this process never terminates.
_LEAK_SCRIPT = """
import asyncio, os, sys
sys.path.insert(0, {repo!r})
os.environ["STATE_BACKEND"] = "sqlite"
os.environ["SQLITE_URL"] = {db!r}
os.environ["ENVIRONMENT"] = "development"

from app.core.durable_state import get_durable_state

async def main():
    store = get_durable_state()
    await store.save_json("k", {{"v": 1}})
    assert store.backend == "sqlite", store.backend

asyncio.run(main())
print("WORK_DONE", flush=True)
# Deliberately no close_durable_state() -- that is the whole point.
"""


def _run_leak_script(tmp_path, extra_env=None):
    """Run the leaking script in a subprocess under a hard timeout.

    Returns (returncode, stdout). A timeout is reported as returncode 124 to
    match the shell convention used elsewhere in this repo's verification.
    """
    import subprocess
    import sys as _sys

    script = _LEAK_SCRIPT.format(
        repo=str(Path(__file__).resolve().parent.parent),
        db=str(tmp_path / "atexit_probe.db"),
    )
    env = {**os.environ, **(extra_env or {})}
    env.pop("DATABASE_URL", None)
    try:
        proc = subprocess.run(
            [_sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    return proc.returncode, proc.stdout


def test_process_exits_when_sqlite_state_is_never_closed(tmp_path):
    """The acceptance gate: a leaked connection must not wedge interpreter exit.

    Asserting on the exit code rather than on output is deliberate. A passing
    log line reads identically whether the process exited or hung -- that
    ambiguity is exactly what let the original six-hour CI hang through.
    """
    returncode, stdout = _run_leak_script(tmp_path)

    assert "WORK_DONE" in stdout, f"script did not complete its work: {stdout!r}"
    assert returncode != 124, (
        "process hung at exit: the aiosqlite worker thread was never released"
    )
    assert returncode == 0, f"unexpected exit code {returncode}"


def test_clean_close_untracks_and_releases_the_worker_thread(tmp_path):
    """The normal path stays authoritative: close() releases and deregisters."""
    import threading

    reset_durable_state_for_tests()
    store = DurableStateStore()
    store._state_backend = "sqlite"
    store._sqlite_url = str(tmp_path / "clean_close.db")

    async def exercise():
        await store.save_json("k", {"v": 1})
        assert store.backend == "sqlite"
        conn = store._sqlite_conn
        assert conn is not None
        assert _TRACKED_SQLITE_CONNECTIONS, "backstop did not track the connection"
        await store.close()
        return conn

    conn = asyncio.run(exercise())

    assert id(conn) not in _TRACKED_SQLITE_CONNECTIONS, (
        "connection still tracked after a clean close"
    )
    assert store._sqlite_owner_pid is None
    conn._thread.join(timeout=10)
    assert not conn._thread.is_alive(), "worker thread outlived close()"
    assert conn._thread not in threading.enumerate()
    reset_durable_state_for_tests()


def test_shutdown_backstop_is_inert_in_a_forked_child(tmp_path, monkeypatch):
    """A forked child must never close a connection its parent owns."""
    reset_durable_state_for_tests()
    store = DurableStateStore()
    store._state_backend = "sqlite"
    store._sqlite_url = str(tmp_path / "fork_guard.db")

    async def setup():
        await store.save_json("k", {"v": 1})

    asyncio.run(setup())
    conn = store._sqlite_conn
    assert conn is not None
    assert id(conn) in _TRACKED_SQLITE_CONNECTIONS

    # Pretend we are a child that inherited the registry across fork().
    monkeypatch.setattr(os, "getpid", lambda: store._sqlite_owner_pid + 1)
    _release_tracked_sqlite_connections()
    assert conn._thread.is_alive(), "child closed a connection it does not own"

    # The real owner still releases it.
    monkeypatch.undo()
    _TRACKED_SQLITE_CONNECTIONS[id(conn)] = (conn, store._sqlite_owner_pid)
    _release_tracked_sqlite_connections()
    conn._thread.join(timeout=10)
    assert not conn._thread.is_alive()

    store._sqlite_conn = None
    store._unregister_sqlite_shutdown_backstop()
    reset_durable_state_for_tests()
