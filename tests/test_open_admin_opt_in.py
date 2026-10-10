"""Unauthenticated local admin requires explicit opt-in.

DEBUG with no keys configured used to make any caller a bootstrap admin.
Now the open-admin path additionally requires
ALLOW_UNAUTHENTICATED_DEV_ADMIN=true, logs a loud warning on boot and per
request, and stays refused in production-like environments even with the
flag set (the boot guardrail refuses that posture entirely).
"""

import logging

import pytest
from fastapi import HTTPException

from app.core.auth import get_auth_context
from app.core.config import get_settings
from app.core.trust_mode import (
    TrustModeGuardrailError,
    validate_trust_mode_config,
    warn_if_open_admin_enabled,
)

UNKNOWN_KEY = "some-unconfigured-caller-key"


@pytest.fixture()
def auth_settings():
    """Snapshot and restore the cached settings fields these tests mutate."""
    settings = get_settings()
    saved = {
        name: getattr(settings, name)
        for name in (
            "ENVIRONMENT",
            "DEBUG",
            "VALID_API_KEYS",
            "STATIC_DEV_API_KEYS",
            "ALLOW_UNAUTHENTICATED_DEV_ADMIN",
        )
    }
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def _debug_no_keys(auth_settings, environment="local"):
    auth_settings.ENVIRONMENT = environment
    auth_settings.DEBUG = True
    auth_settings.VALID_API_KEYS = ""
    auth_settings.STATIC_DEV_API_KEYS = ""
    auth_settings.ALLOW_UNAUTHENTICATED_DEV_ADMIN = False


async def test_open_admin_denied_without_flag(auth_settings):
    """DEBUG plus no keys is not enough: unknown keys fail closed."""
    _debug_no_keys(auth_settings)

    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=UNKNOWN_KEY)
    assert exc.value.status_code == 403


async def test_open_admin_granted_with_flag_locally(auth_settings, caplog):
    """With the explicit opt-in, local DEBUG with no keys mints an admin."""
    _debug_no_keys(auth_settings)
    auth_settings.ALLOW_UNAUTHENTICATED_DEV_ADMIN = True

    with caplog.at_level(logging.WARNING, logger="app.core.auth"):
        context = await get_auth_context(api_key=UNKNOWN_KEY)

    assert context.is_bootstrap_admin is True
    assert context.source == "env"
    context.require_bootstrap_admin()  # must not raise
    assert any("open_admin_auth" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("environment", ["production", "staging"])
async def test_open_admin_refused_production_like_with_flag(auth_settings, environment):
    """The flag never opens admin in production-like environments."""
    _debug_no_keys(auth_settings, environment=environment)
    auth_settings.ALLOW_UNAUTHENTICATED_DEV_ADMIN = True

    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=UNKNOWN_KEY)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_guardrail_rejects_flag_in_production_like(environment):
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment=environment,
            trust_mode_enabled=True,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            allow_unauthenticated_dev_admin=True,
        )
    assert "ALLOW_UNAUTHENTICATED_DEV_ADMIN" in str(exc_info.value)


def test_guardrail_allows_flag_locally():
    validate_trust_mode_config(
        environment="local",
        trust_mode_enabled=True,
        signing_private_key_b64="",
        allow_legacy_unpermitted_mcp=True,
        allow_unauthenticated_dev_admin=True,
    )


def test_boot_warning_fires_only_when_opted_in_locally(auth_settings, caplog):
    auth_settings.ENVIRONMENT = "local"
    auth_settings.ALLOW_UNAUTHENTICATED_DEV_ADMIN = True
    with caplog.at_level(logging.WARNING, logger="app.core.trust_mode"):
        warn_if_open_admin_enabled(auth_settings)
    assert any("open_admin_enabled" in record.getMessage() for record in caplog.records)

    caplog.clear()
    auth_settings.ALLOW_UNAUTHENTICATED_DEV_ADMIN = False
    with caplog.at_level(logging.WARNING, logger="app.core.trust_mode"):
        warn_if_open_admin_enabled(auth_settings)
    assert not any(
        "open_admin_enabled" in record.getMessage() for record in caplog.records
    )
