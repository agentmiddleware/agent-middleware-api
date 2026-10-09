"""Focused tests for app.core.config (Settings defaults, validation, helpers)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import (
    DuplicateGuardMode,
    Settings,
    get_settings,
    public_api_origin,
)


@pytest.fixture
def _clean_settings_cache():
    """Yield with a fresh settings cache, then restore it."""
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_defaults_match_documented_values(monkeypatch):
    # conftest sets several of these for the suite, so clear them to read
    # the true class defaults rather than the ambient test environment.
    for key in (
        "APP_NAME",
        "ENVIRONMENT",
        "DEBUG",
        "TRUST_MODE_ENABLED",
        "ALLOW_LEGACY_UNPERMITTED_MCP",
        "MCP_UPSTREAM_DUPLICATE_GUARD",
        "EXCHANGE_RATE",
        "PUBLIC_URL",
        "ENABLE_PROOF_SURFACES",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.APP_NAME == "Agent Middleware API"
    assert settings.ENVIRONMENT == "local"
    assert settings.DEBUG is False
    assert settings.TRUST_MODE_ENABLED is True
    assert settings.ALLOW_LEGACY_UNPERMITTED_MCP is False
    assert settings.MCP_UPSTREAM_DUPLICATE_GUARD == DuplicateGuardMode.LOG
    assert settings.EXCHANGE_RATE == Decimal("1000.0")
    assert settings.PUBLIC_URL == ""
    assert settings.ENABLE_PROOF_SURFACES is False


def test_exchange_rate_accepts_positive_decimal():
    settings = Settings(EXCHANGE_RATE=Decimal("2500.5"))
    assert settings.EXCHANGE_RATE == Decimal("2500.5")


@pytest.mark.parametrize("bad_rate", [Decimal("0"), Decimal("-1"), Decimal("-1000.0")])
def test_exchange_rate_zero_or_negative_rejected(bad_rate):
    with pytest.raises(ValidationError) as exc_info:
        Settings(EXCHANGE_RATE=bad_rate)
    assert "EXCHANGE_RATE" in str(exc_info.value)


def test_exchange_rate_zero_string_rejected():
    with pytest.raises(ValidationError):
        Settings(EXCHANGE_RATE="0")


def test_invalid_duplicate_guard_mode_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Settings(MCP_UPSTREAM_DUPLICATE_GUARD="sometimes")
    assert "MCP_UPSTREAM_DUPLICATE_GUARD" in str(exc_info.value)


def test_invalid_port_type_rejected():
    with pytest.raises(ValidationError):
        Settings(PORT="not-a-port")


def test_get_settings_returns_cached_singleton(_clean_settings_cache):
    assert get_settings() is get_settings()


def test_public_api_origin_empty_by_default(_clean_settings_cache):
    settings = get_settings()
    previous = settings.PUBLIC_URL
    settings.PUBLIC_URL = ""
    try:
        assert public_api_origin() == ""
    finally:
        settings.PUBLIC_URL = previous


def test_public_api_origin_strips_whitespace_and_trailing_slash(_clean_settings_cache):
    settings = get_settings()
    previous = settings.PUBLIC_URL
    settings.PUBLIC_URL = "  https://example.com/api///  "
    try:
        assert public_api_origin() == "https://example.com/api"
    finally:
        settings.PUBLIC_URL = previous


def test_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Config Probe Name")
    assert Settings().APP_NAME == "Config Probe Name"
