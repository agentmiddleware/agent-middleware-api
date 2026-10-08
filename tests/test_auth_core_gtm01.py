"""GTM-01 auth-core regressions: DEBUG open-admin opt-in and charge scopes.

Covers two findings from the go-to-market auth review:

- DEBUG open mode (any unknown key becomes bootstrap admin with DEBUG on
  and no keys configured) now needs the explicit local-only opt-in
  ``ALLOW_DEBUG_OPEN_AUTH=true``; every other posture fails closed.
- ``POST /v1/billing/charge`` enforces the ``billing:charge`` JWT scope,
  so scope-limited tokens are actually checked on the money path.
"""

import base64

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_auth_context
from app.core.config import get_settings
from app.core.jwt import get_jwt_service
from app.core.trust_mode import (
    TrustModeGuardrailError,
    validate_trust_mode_config,
)
from app.db.database import get_session_factory
from app.db.models import WalletModel
from app.services.api_key_service import get_api_key_service


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
            "ALLOW_DEBUG_OPEN_AUTH",
            "TRUST_SIGNING_PRIVATE_KEY_B64",
        )
    }
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def _open_mode_settings(auth_settings):
    auth_settings.ENVIRONMENT = "local"
    auth_settings.DEBUG = True
    auth_settings.VALID_API_KEYS = ""
    auth_settings.STATIC_DEV_API_KEYS = ""


async def test_debug_open_mode_fails_closed_without_opt_in(auth_settings):
    """DEBUG on with no keys must refuse an unknown key, not crown it."""
    _open_mode_settings(auth_settings)
    auth_settings.ALLOW_DEBUG_OPEN_AUTH = False

    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="some-unknown-key-value")

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "invalid_api_key"


async def test_debug_open_mode_grants_admin_with_opt_in(auth_settings):
    """The explicit local-only opt-in preserves the old dev convenience."""
    _open_mode_settings(auth_settings)
    auth_settings.ALLOW_DEBUG_OPEN_AUTH = True

    context = await get_auth_context(api_key="some-unknown-key-value")

    assert context.is_bootstrap_admin is True
    assert context.source == "env"


async def test_debug_open_mode_opt_in_still_closed_in_production(auth_settings):
    """Even with the flag, a production-like boot never grants open admin."""
    auth_settings.ENVIRONMENT = "production"
    auth_settings.DEBUG = True
    auth_settings.VALID_API_KEYS = ""
    auth_settings.STATIC_DEV_API_KEYS = ""
    auth_settings.ALLOW_DEBUG_OPEN_AUTH = True

    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="some-unknown-key-value")

    assert exc.value.status_code == 403


def test_guardrail_rejects_debug_open_auth_in_production():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            allow_debug_open_auth=True,
        )
    assert "ALLOW_DEBUG_OPEN_AUTH" in str(exc_info.value)


def test_guardrail_allows_debug_open_auth_locally():
    validate_trust_mode_config(
        environment="local",
        trust_mode_enabled=True,
        signing_private_key_b64="",
        allow_legacy_unpermitted_mcp=True,
        enable_proof_surfaces=False,
        allow_debug_open_auth=True,
    )


def test_shipped_default_is_closed():
    from app.core.config import Settings

    assert Settings.model_fields["ALLOW_DEBUG_OPEN_AUTH"].default is False


async def _seed_wallet_key(wallet_id: str):
    async with get_session_factory()() as session:
        session.add(WalletModel(wallet_id=wallet_id, wallet_type="agent"))
        await session.commit()
    return await get_api_key_service().create_key(wallet_id)


@pytest.mark.anyio
async def test_charge_rejects_jwt_without_billing_charge_scope(
    clean_database, auth_settings, monkeypatch
):
    """A scope-limited JWT cannot move money: 403 insufficient_scope."""
    from app.main import app

    monkeypatch.setattr(
        get_settings(),
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(bytes(range(32))).decode(),
    )
    key = await _seed_wallet_key("qa_charge_scope_denied")
    token = get_jwt_service().create_access_token(
        wallet_id="qa_charge_scope_denied",
        key_id=key["key_id"],
        scopes=["billing:read"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post(
            "/v1/billing/charge?wallet_id=qa_charge_scope_denied"
            "&service=agent_comms&units=1",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "insufficient_scope"


@pytest.mark.anyio
async def test_charge_accepts_jwt_with_billing_charge_scope(
    clean_database, auth_settings, monkeypatch
):
    """A correctly scoped JWT passes the scope gate (wallet check decides)."""
    from app.main import app

    monkeypatch.setattr(
        get_settings(),
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(bytes(range(32))).decode(),
    )
    key = await _seed_wallet_key("qa_charge_scope_allowed")
    token = get_jwt_service().create_access_token(
        wallet_id="qa_charge_scope_allowed",
        key_id=key["key_id"],
        scopes=["billing:charge"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post(
            "/v1/billing/charge?wallet_id=no-such-wallet&service=agent_comms&units=1",
            headers={"Authorization": f"Bearer {token}"},
        )

    # Past the scope gate: the wallet check, not the scope check, refuses.
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "wallet_access_denied"
