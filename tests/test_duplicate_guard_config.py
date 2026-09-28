"""Unit tests for duplicate guard configuration validation."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import DuplicateGuardMode, Settings
from app.main import app


@pytest_asyncio.fixture
async def client():
    """AsyncClient for testing HTTP endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


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


def test_repeat_window_seconds_rejects_zero_and_negative():
    """repeat_window_seconds must be positive."""
    from app.schemas.trust import PermitCreateRequest
    
    # Zero is rejected
    with pytest.raises(ValidationError) as exc_info:
        PermitCreateRequest(
            issuer_wallet_id="iss-1",
            subject_wallet_id="sub-1",
            allowed_tools=["tool"],
            scopes=["scope"],
            max_credits=100,
            expires_at="2026-12-31T23:59:59Z",
            repeat_window_seconds=0,
        )
    assert "repeat_window_seconds" in str(exc_info.value)
    
    # Negative is rejected
    with pytest.raises(ValidationError) as exc_info:
        PermitCreateRequest(
            issuer_wallet_id="iss-1",
            subject_wallet_id="sub-1",
            allowed_tools=["tool"],
            scopes=["scope"],
            max_credits=100,
            expires_at="2026-12-31T23:59:59Z",
            repeat_window_seconds=-1,
        )
    assert "repeat_window_seconds" in str(exc_info.value)


@pytest.mark.anyio
async def test_duplicate_guard_health_endpoint_requires_admin_auth(client):
    """GET /health/duplicate-guard requires bootstrap admin authentication."""
    # Without auth header - should fail
    r = await client.get("/health/duplicate-guard")
    assert r.status_code == 401
    
    # With bootstrap admin key - should succeed
    from tests.test_trust_helpers import BOOTSTRAP_HEADERS
    r = await client.get("/health/duplicate-guard", headers=BOOTSTRAP_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "mode" in body
    assert "log_mode_blocks" in body
    assert "enforce_mode_blocks" in body
    assert "window_seconds" in body


def test_repeat_window_seconds_rejects_excessive_values():
    """repeat_window_seconds has a maximum of 365 days."""
    from app.schemas.trust import PermitCreateRequest
    
    # 365 days is accepted
    PermitCreateRequest(
        issuer_wallet_id="iss-1",
        subject_wallet_id="sub-1",
        allowed_tools=["tool"],
        scopes=["scope"],
        max_credits=100,
        expires_at="2026-12-31T23:59:59Z",
        repeat_window_seconds=31536000,
    )
    
    # Over 365 days is rejected
    with pytest.raises(ValidationError) as exc_info:
        PermitCreateRequest(
            issuer_wallet_id="iss-1",
            subject_wallet_id="sub-1",
            allowed_tools=["tool"],
            scopes=["scope"],
            max_credits=100,
            expires_at="2026-12-31T23:59:59Z",
            repeat_window_seconds=31536001,
        )
    assert "repeat_window_seconds" in str(exc_info.value)
