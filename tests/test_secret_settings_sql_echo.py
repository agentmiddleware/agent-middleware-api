"""Secret settings stay masked, and DEBUG alone never enables SQL echo.

Stripe, Sentinel, and model keys are pydantic SecretStr so settings dumps,
reprs, and logs carry the mask instead of the value. SQL statement logging
(SQLAlchemy echo, which records bound values) is gated by the explicit
SQL_ECHO flag only: DEBUG must never turn it on by itself.
"""

import pytest
from pydantic import SecretStr

from app.core.config import Settings, get_settings


def test_secret_settings_use_secret_str():
    cfg = Settings()
    assert isinstance(cfg.STRIPE_SECRET_KEY, SecretStr)
    assert isinstance(cfg.STRIPE_WEBHOOK_SECRET, SecretStr)
    assert isinstance(cfg.SENTINEL_API_KEY, SecretStr)
    assert isinstance(cfg.LLM_API_KEY, SecretStr)


def test_settings_repr_masks_secret_values():
    stripe_secret = "sk-test-only-for-repr-check-0001"
    webhook_secret = "whsec-only-for-repr-check-0002"
    sentinel_secret = "sentinel-only-for-repr-check-0003"
    llm_secret = "llm-only-for-repr-check-0004"
    cfg = Settings(
        STRIPE_SECRET_KEY=stripe_secret,
        STRIPE_WEBHOOK_SECRET=webhook_secret,
        SENTINEL_API_KEY=sentinel_secret,
        LLM_API_KEY=llm_secret,
    )
    assert cfg.STRIPE_SECRET_KEY.get_secret_value() == stripe_secret
    assert cfg.STRIPE_WEBHOOK_SECRET.get_secret_value() == webhook_secret
    assert cfg.SENTINEL_API_KEY.get_secret_value() == sentinel_secret
    assert cfg.LLM_API_KEY.get_secret_value() == llm_secret
    rendered = repr(cfg)
    assert stripe_secret not in rendered
    assert webhook_secret not in rendered
    assert sentinel_secret not in rendered
    assert llm_secret not in rendered


def test_debug_alone_does_not_enable_sql_echo():
    cfg = Settings(DEBUG=True)
    assert cfg.DEBUG is True
    assert cfg.SQL_ECHO is False


def test_sql_echo_is_explicit_opt_in():
    assert Settings().SQL_ECHO is False
    assert Settings(SQL_ECHO=True).SQL_ECHO is True


@pytest.mark.anyio
async def test_engine_echo_follows_sql_echo_not_debug(monkeypatch, tmp_path):
    """DEBUG=true with default SQL_ECHO must build a silent engine."""
    import app.db.database as db_mod

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/echo.db")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.delenv("SQL_ECHO", raising=False)
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None
    try:
        assert get_settings().DEBUG is True
        assert get_settings().SQL_ECHO is False
        engine = db_mod.get_engine()
        assert engine is not None
        assert engine.echo is False
    finally:
        await db_mod.close_db()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_engine_echo_enabled_by_explicit_sql_echo(monkeypatch, tmp_path):
    """SQL_ECHO=true opts into statement logging on purpose."""
    import app.db.database as db_mod

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/echo.db")
    monkeypatch.setenv("SQL_ECHO", "true")
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None
    try:
        assert get_settings().SQL_ECHO is True
        engine = db_mod.get_engine()
        assert engine is not None
        assert engine.echo is True
    finally:
        await db_mod.close_db()
        get_settings.cache_clear()
