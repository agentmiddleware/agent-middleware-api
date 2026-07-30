"""DATABASE_URL normalization and durable-state fail-closed behavior."""

from __future__ import annotations

import pytest

from app.core.db_urls import as_asyncpg_url, as_sqlalchemy_url
from app.core.durable_state import (
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


def test_url_helpers_are_idempotent():
    raw = "postgresql://u:p@h/db"
    sa = as_sqlalchemy_url(raw)
    assert as_sqlalchemy_url(sa) == sa
    assert as_asyncpg_url(as_asyncpg_url(sa)) == as_asyncpg_url(sa)
    assert as_asyncpg_url(sa) == raw


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
