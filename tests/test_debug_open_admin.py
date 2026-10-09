"""Development open-admin mode requires explicit opt-in.

With DEBUG on, no keys configured, and a local environment, any caller
used to authenticate as a bootstrap admin. That fallback now also
requires ALLOW_DEBUG_OPEN_ADMIN, and every boot with the mode armed logs
a warning at startup (plus one per grant).
"""

import logging

import pytest
from fastapi import HTTPException

from app.core.auth import get_auth_context
from app.core.config import get_settings
from app.core.trust_mode import (
    TrustModeGuardrailError,
    describe_permissive_trust_mode,
    validate_trust_mode_config,
    warn_if_debug_open_admin,
)


@pytest.fixture()
def open_admin_settings():
    """Snapshot and restore the cached settings fields these tests mutate."""
    settings = get_settings()
    saved = {
        name: getattr(settings, name)
        for name in (
            "ENVIRONMENT",
            "DEBUG",
            "VALID_API_KEYS",
            "STATIC_DEV_API_KEYS",
            "ALLOW_DEBUG_OPEN_ADMIN",
        )
    }
    settings.ENVIRONMENT = "local"
    settings.DEBUG = True
    settings.VALID_API_KEYS = ""
    settings.STATIC_DEV_API_KEYS = ""
    settings.ALLOW_DEBUG_OPEN_ADMIN = False
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


@pytest.mark.anyio
async def test_debug_without_opt_in_fails_closed(open_admin_settings):
    """DEBUG alone never grants admin to an unknown key."""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="some-unknown-local-key")
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_debug_with_opt_in_grants_admin_and_logs(open_admin_settings, caplog):
    """Explicit opt-in restores the local fallback and logs each grant."""
    open_admin_settings.ALLOW_DEBUG_OPEN_ADMIN = True
    with caplog.at_level(logging.WARNING, logger="app.core.auth"):
        context = await get_auth_context(api_key="some-unknown-local-key")
    assert context.is_bootstrap_admin is True
    assert context.source == "env"
    assert any("debug_open_admin_grant" in record.message for record in caplog.records)


@pytest.mark.anyio
async def test_opt_in_with_configured_keys_stays_closed(open_admin_settings):
    """Configured keys close the mode even when the opt-in flag is set."""
    open_admin_settings.ALLOW_DEBUG_OPEN_ADMIN = True
    open_admin_settings.VALID_API_KEYS = "test-key"
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="not-the-configured-key")
    assert exc.value.status_code == 403


def test_guardrail_rejects_opt_in_in_production():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            debug=False,
            allow_debug_open_admin=True,
        )
    assert "ALLOW_DEBUG_OPEN_ADMIN" in str(exc_info.value)


def test_startup_warning_logs_only_when_mode_armed(open_admin_settings, caplog):
    """The boot log fires exactly when an unknown key would become admin."""
    open_admin_settings.ALLOW_DEBUG_OPEN_ADMIN = True
    with caplog.at_level(logging.WARNING, logger="app.core.trust_mode"):
        warn_if_debug_open_admin(open_admin_settings)
    assert any(
        "debug_open_admin_enabled" in record.message for record in caplog.records
    )

    caplog.clear()
    open_admin_settings.ALLOW_DEBUG_OPEN_ADMIN = False
    with caplog.at_level(logging.WARNING, logger="app.core.trust_mode"):
        warn_if_debug_open_admin(open_admin_settings)
    assert not any(
        "debug_open_admin_enabled" in record.message for record in caplog.records
    )


def test_permissive_description_names_opt_in():
    description = describe_permissive_trust_mode(
        trust_mode_enabled=True,
        allow_legacy_unpermitted_mcp=False,
        allow_debug_open_admin=True,
    )
    assert description is not None
    assert "ALLOW_DEBUG_OPEN_ADMIN" in description
    assert (
        describe_permissive_trust_mode(
            trust_mode_enabled=True,
            allow_legacy_unpermitted_mcp=False,
        )
        is None
    )
