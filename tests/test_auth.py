"""Focused coverage for the API credential layer (app/core/auth.py).

Covers the main public behavior: env key authentication, missing and
malformed credentials, the fail-closed unknown key path, the local DEBUG
open mode, strict Bearer [REDACTED] parsing, the Authorization header taking
precedence over any concurrent API key, the wallet and admin guards on
AuthContext, the static dev key prefix rule, the credential acceptance
signal, and the optional enterprise principal layer staying out of the way
when it is not configured.

No network, no database rows, no external services. Tests only.
"""

import pytest
from fastapi import HTTPException, Request

from app.core.auth import (
    CREDENTIAL_ACCEPTANCE,
    CREDENTIAL_REJECTED_HEADER,
    STATIC_DEV_KEY_PREFIX,
    AuthContext,
    _parse_bearer_authorization,
    _parse_static_dev_keys,
    get_auth_context,
    get_enterprise_principal,
    reject_anonymous_production_catalog,
    verify_api_key,
)
from app.core.auth import CredentialAcceptance
from app.core.config import get_settings

ENV_KEY = "test-key-for-auth-module-tests"


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
            "ENABLE_DEV_KEY_SELF_PROVISION",
            "IGA_TRUSTED_ISSUERS",
        )
    }
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


@pytest.fixture()
def local_locked_settings(auth_settings):
    """Local environment with exactly one valid env key and no open mode."""
    auth_settings.ENVIRONMENT = "local"
    auth_settings.DEBUG = False
    auth_settings.VALID_API_KEYS = ENV_KEY
    auth_settings.STATIC_DEV_API_KEYS = ""
    auth_settings.ENABLE_DEV_KEY_SELF_PROVISION = False
    return auth_settings


def test_auth_context_scopes_default_to_empty_list():
    context = AuthContext(source="env", raw_key="k")
    assert context.scopes == []


def test_require_bootstrap_admin_allows_admin():
    context = AuthContext(source="env", raw_key="k", is_bootstrap_admin=True)
    context.require_bootstrap_admin()  # must not raise


def test_require_bootstrap_admin_denies_non_admin():
    context = AuthContext(source="db", raw_key="k", wallet_id="w1")
    with pytest.raises(HTTPException) as exc:
        context.require_bootstrap_admin()
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "admin_access_denied"


def test_require_wallet_access_allows_admin_for_any_wallet():
    context = AuthContext(source="env", raw_key="k", is_bootstrap_admin=True)
    context.require_wallet_access("some-other-wallet")
    context.require_wallet_access(None)


def test_require_wallet_access_allows_owning_wallet():
    context = AuthContext(source="db", raw_key="k", key_id="key1", wallet_id="wallet-1")
    context.require_wallet_access("wallet-1")  # must not raise


def test_require_wallet_access_denies_other_wallet():
    context = AuthContext(source="db", raw_key="k", key_id="key1", wallet_id="wallet-1")
    with pytest.raises(HTTPException) as exc:
        context.require_wallet_access("wallet-2")
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "wallet_access_denied"


def test_require_wallet_access_denies_ownerless_resource_to_non_admin():
    """A resource with no owning wallet is admin only."""
    context = AuthContext(source="db", raw_key="k", key_id="key1", wallet_id="wallet-1")
    with pytest.raises(HTTPException) as exc:
        context.require_wallet_access(None)
    assert exc.value.status_code == 403


async def test_env_key_authenticates_as_bootstrap_admin(local_locked_settings):
    context = await get_auth_context(api_key=ENV_KEY)
    assert context.source == "env"
    assert context.is_bootstrap_admin is True
    assert context.raw_key == ENV_KEY


async def test_env_key_with_surrounding_whitespace(local_locked_settings):
    context = await get_auth_context(api_key=f"  {ENV_KEY}  ")
    assert context.is_bootstrap_admin is True
    assert context.raw_key == ENV_KEY


async def test_missing_credentials_rejected(local_locked_settings):
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "missing_credentials"


async def test_short_key_rejected(local_locked_settings):
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="short")
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_api_key"


async def test_whitespace_only_key_rejected(local_locked_settings):
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="        ")
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_api_key"


async def test_unknown_key_fails_closed(local_locked_settings):
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="unknown-key-that-is-long-enough")
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "invalid_api_key"
    assert exc.value.headers[CREDENTIAL_REJECTED_HEADER] == "1"


async def test_debug_open_mode_admits_unknown_key_locally(auth_settings):
    auth_settings.ENVIRONMENT = "local"
    auth_settings.DEBUG = True
    auth_settings.VALID_API_KEYS = ""
    auth_settings.STATIC_DEV_API_KEYS = ""
    context = await get_auth_context(api_key="some-unconfigured-local-key")
    assert context.source == "env"
    assert context.is_bootstrap_admin is True


async def test_debug_open_mode_stays_closed_in_production(auth_settings):
    auth_settings.ENVIRONMENT = "production"
    auth_settings.DEBUG = True
    auth_settings.VALID_API_KEYS = ""
    auth_settings.STATIC_DEV_API_KEYS = ""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="some-unconfigured-local-key")
    assert exc.value.status_code == 403


def test_parse_bearer_authorization_accepts_well_formed_header():
    assert _parse_bearer_authorization("Bearer some-token-value") == "some-token-value"


def test_parse_bearer_authorization_rejects_wrong_scheme():
    with pytest.raises(HTTPException) as exc:
        _parse_bearer_authorization("Token some-token-value")
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_token"


def test_parse_bearer_authorization_rejects_empty_token():
    with pytest.raises(HTTPException) as exc:
        _parse_bearer_authorization("Bearer ")
    assert exc.value.status_code == 401


def test_parse_bearer_authorization_rejects_inner_whitespace():
    with pytest.raises(HTTPException) as exc:
        _parse_bearer_authorization("Bearer token with spaces")
    assert exc.value.status_code == 401


def test_parse_bearer_authorization_rejects_padded_token():
    with pytest.raises(HTTPException) as exc:
        _parse_bearer_authorization("Bearer padded-token ")
    assert exc.value.status_code == 401


async def test_authorization_header_is_authoritative_over_api_key(
    local_locked_settings,
):
    """A malformed Authorization header never falls back to a valid API key."""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=ENV_KEY, authorization="Token not-bearer")
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_token"


async def test_invalid_bearer_token_rejected_despite_valid_api_key(
    local_locked_settings,
):
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=ENV_KEY, authorization="Bearer not-a-real-token")
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_token"


async def test_bearer_prefixed_api_key_treated_as_token(local_locked_settings):
    """The direct-call compatibility path verifies Bearer [REDACTED] as JWT."""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="Bearer not-a-real-token")
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_token"


def test_parse_static_dev_keys_keeps_only_prefixed_entries():
    parsed = _parse_static_dev_keys(
        f" {STATIC_DEV_KEY_PREFIX}one , amw_live_wrong-variable ,"
        f" {STATIC_DEV_KEY_PREFIX}two "
    )
    assert parsed == [f"{STATIC_DEV_KEY_PREFIX}one", f"{STATIC_DEV_KEY_PREFIX}two"]


def test_parse_static_dev_keys_empty_config_parses_to_empty():
    assert _parse_static_dev_keys("") == []
    assert _parse_static_dev_keys("   ") == []


async def test_credential_acceptance_marked_on_success(local_locked_settings):
    acceptance = CredentialAcceptance()
    token = CREDENTIAL_ACCEPTANCE.set(acceptance)
    try:
        await get_auth_context(api_key=ENV_KEY)
    finally:
        CREDENTIAL_ACCEPTANCE.reset(token)
    assert acceptance.accepted is True


async def test_verify_api_key_returns_raw_key(local_locked_settings):
    assert await verify_api_key(api_key=ENV_KEY) == ENV_KEY


async def test_verify_api_key_rejects_missing_credentials(local_locked_settings):
    with pytest.raises(HTTPException) as exc:
        await verify_api_key(api_key=None)
    assert exc.value.status_code == 401


async def test_get_enterprise_principal_returns_none_when_unconfigured(
    auth_settings,
):
    auth_settings.IGA_TRUSTED_ISSUERS = ""
    assert await get_enterprise_principal(authorization=None) is None
    assert await get_enterprise_principal(authorization="X-API-Key test-key") is None
    assert (
        await get_enterprise_principal(authorization="Bearer not-a-real-token") is None
    )


def _request_with_headers(headers: dict) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request(scope={"type": "http", "headers": raw})


async def test_reject_anonymous_catalog_is_noop_locally(auth_settings):
    auth_settings.ENVIRONMENT = "local"
    await reject_anonymous_production_catalog(_request_with_headers({}))


async def test_reject_anonymous_catalog_requires_auth_in_production(auth_settings):
    auth_settings.ENVIRONMENT = "production"
    auth_settings.DEBUG = False
    auth_settings.VALID_API_KEYS = ENV_KEY
    auth_settings.STATIC_DEV_API_KEYS = ""
    with pytest.raises(HTTPException):
        await reject_anonymous_production_catalog(_request_with_headers({}))
