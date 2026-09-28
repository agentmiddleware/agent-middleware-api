"""Unit tests for duplicate guard configuration validation."""

import pytest
from pydantic import ValidationError

from app.core.config import DuplicateGuardMode, Settings


def test_duplicate_guard_mode_enum_values():
    """Duplicate guard mode enum has expected values."""
    assert DuplicateGuardMode.OFF.value == "off"
    assert DuplicateGuardMode.LOG.value == "log"
    assert DuplicateGuardMode.ENFORCE.value == "enforce"
    # Enum members are strings for config compatibility
    assert isinstance(DuplicateGuardMode.LOG, str)


def test_duplicate_guard_mode_invalid_value_rejected():
    """Invalid duplicate guard mode values are rejected at startup."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            VALID_API_KEYS="test-key",
            MCP_UPSTREAM_DUPLICATE_GUARD="enforced",  # typo
        )
    error = str(exc_info.value)
    assert "MCP_UPSTREAM_DUPLICATE_GUARD" in error


def test_duplicate_guard_mode_default_is_log():
    """Default duplicate guard mode is log (observe-only)."""
    settings = Settings(VALID_API_KEYS="test-key")
    assert settings.MCP_UPSTREAM_DUPLICATE_GUARD == DuplicateGuardMode.LOG


def test_duplicate_guard_mode_off_accepted():
    """OFF mode disables duplicate detection."""
    settings = Settings(
        VALID_API_KEYS="test-key",
        MCP_UPSTREAM_DUPLICATE_GUARD="off",
    )
    assert settings.MCP_UPSTREAM_DUPLICATE_GUARD == DuplicateGuardMode.OFF


def test_duplicate_guard_mode_enforce_accepted():
    """ENFORCE mode blocks duplicates."""
    settings = Settings(
        VALID_API_KEYS="test-key",
        MCP_UPSTREAM_DUPLICATE_GUARD="enforce",
    )
    assert settings.MCP_UPSTREAM_DUPLICATE_GUARD == DuplicateGuardMode.ENFORCE


def test_duplicate_guard_window_default():
    """Default duplicate window is 24 hours."""
    settings = Settings(VALID_API_KEYS="test-key")
    assert settings.MCP_UPSTREAM_DUPLICATE_WINDOW_SECONDS == 86400
