"""Fail-closed hardening defaults (go-to-market fix #5).

Each group below closes one permissive default behind a clear config flag
(see the "Fail-closed hardening" section in app/core/config.py):

- REQUIRE_JWT_SCOPES (default True): routes decorated with
  app.core.scopes.require_scope enforce JWT scopes. Money routes
  (billing charge/transfer, ACP checkout) require billing:charge and
  permit issuance requires tool:invoke. API-key callers bypass, JWT
  callers with an attenuated scope set get 403 insufficient_scope.
- DEBUG_ALLOW_OPEN_ADMIN (default False): DEBUG mode with no keys
  configured denies unknown keys instead of granting bootstrap admin.
- POLICY_DENY_EMPTY_BUNDLES (default True): a wallet with no active
  policy bundles is denied (policy_no_bundles) instead of allowed.
- POLICY_DENY_UNKNOWN_COST (default True): a capped check that cannot
  be evaluated because the cost estimate is unknown is denied instead
  of skipped.

The suite opts the two policy flags back to permissive in
tests/conftest.py, so these tests set them explicitly in both positions.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_auth_context
from app.core.config import get_settings
from app.core.jwt import get_jwt_service
from app.db.database import get_session_factory
from app.db.models import WalletModel
from app.main import app
from app.schemas.policies import PolicyBundleCreate
from app.services.api_key_service import get_api_key_service
from app.services.policies import create_policy_bundle, evaluate_wallet_policy

# 32 raw bytes, strict base64. Same non-secret test material CI uses
# (see tests/test_jwt_auth.py).
TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
def hardening_settings():
    """Snapshot and restore every settings field these tests mutate."""
    settings = get_settings()
    saved = {
        name: getattr(settings, name)
        for name in (
            "ENVIRONMENT",
            "DEBUG",
            "VALID_API_KEYS",
            "STATIC_DEV_API_KEYS",
            "REQUIRE_JWT_SCOPES",
            "DEBUG_ALLOW_OPEN_ADMIN",
            "POLICY_DENY_EMPTY_BUNDLES",
            "POLICY_DENY_UNKNOWN_COST",
            "TRUST_SIGNING_PRIVATE_KEY_B64",
        )
    }
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


async def _funded_agent_wallet(client: AsyncClient) -> str:
    """Create a sponsor plus a funded agent wallet using the bootstrap key."""
    admin = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "scope test sponsor",
            "email": "scope@example.com",
            "initial_credits": 10000,
            "require_kyc": False,
        },
        headers=admin,
    )
    assert sponsor.status_code == 201, sponsor.text
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor.json()["wallet_id"],
            "agent_id": "scope-agent",
            "budget_credits": 5000,
        },
        headers=admin,
    )
    assert agent.status_code == 201, agent.text
    return agent.json()["wallet_id"]


async def _jwt_for_wallet(client: AsyncClient, wallet_id: str, scopes) -> str:
    """Mint a JWT directly: /v1/auth/token is not mounted on the main app.

    ``scopes=None`` reproduces the exchange default (billing:charge plus
    tool:invoke, see app/routers/auth.py).
    """
    del client
    settings = get_settings()
    if not settings.TRUST_SIGNING_PRIVATE_KEY_B64.strip():
        settings.TRUST_SIGNING_PRIVATE_KEY_B64 = TEST_SIGNING_KEY
    key = await get_api_key_service().create_key(wallet_id)
    return get_jwt_service().create_access_token(
        wallet_id=wallet_id,
        key_id=key["key_id"],
        scopes=["billing:charge", "tool:invoke"] if scopes is None else scopes,
    )


async def _ensure_wallet(wallet_id: str) -> None:
    """Policy bundles reference wallets, so the wallet row must exist first."""
    async with get_session_factory()() as session:
        session.add(WalletModel(wallet_id=wallet_id, wallet_type="agent"))
        await session.commit()


def _charge(client: AsyncClient, wallet_id: str, token: str):
    return client.post(
        f"/v1/billing/charge?wallet_id={wallet_id}&service=agent_comms&units=5",
        headers={"Authorization": f"Bearer {token}"},
    )


# --- JWT scope enforcement on money and permit routes ---


@pytest.mark.anyio
async def test_charge_denies_read_scoped_jwt(
    client, clean_database, hardening_settings
):
    """An attenuated JWT (billing:read) cannot move money: 403, no debit."""
    wallet_id = await _funded_agent_wallet(client)
    token = await _jwt_for_wallet(client, wallet_id, ["billing:read"])

    before = (
        await client.get(
            f"/v1/billing/wallets/{wallet_id}", headers={"X-API-Key": "test-key"}
        )
    ).json()["balance"]

    resp = await _charge(client, wallet_id, token)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "insufficient_scope"

    after = (
        await client.get(
            f"/v1/billing/wallets/{wallet_id}", headers={"X-API-Key": "test-key"}
        )
    ).json()["balance"]
    assert after == before


@pytest.mark.anyio
async def test_charge_allows_default_scoped_jwt(
    client, clean_database, hardening_settings
):
    """Wiring scopes does not break the normal JWT path (default scopes)."""
    hardening_settings.POLICY_DENY_EMPTY_BUNDLES = False
    wallet_id = await _funded_agent_wallet(client)
    token = await _jwt_for_wallet(client, wallet_id, None)

    resp = await _charge(client, wallet_id, token)

    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
async def test_scope_enforcement_opt_out_passes_attenuated_jwt(
    client, clean_database, hardening_settings
):
    """REQUIRE_JWT_SCOPES=false restores the old pass-through posture."""
    hardening_settings.REQUIRE_JWT_SCOPES = False
    hardening_settings.POLICY_DENY_EMPTY_BUNDLES = False
    wallet_id = await _funded_agent_wallet(client)
    token = await _jwt_for_wallet(client, wallet_id, ["billing:read"])

    resp = await _charge(client, wallet_id, token)

    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
async def test_permit_create_denies_read_scoped_jwt(
    client, clean_database, hardening_settings
):
    """An attenuated JWT cannot mint permits even with a valid idempotency key."""
    wallet_id = await _funded_agent_wallet(client)
    token = await _jwt_for_wallet(client, wallet_id, ["billing:read"])

    resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "scopes": ["tool:invoke"],
            "allowed_tools": ["notes.write"],
            "max_credits": 10,
            "expires_at": "2030-01-01T00:00:00Z",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "scope-test-key-1",
        },
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "insufficient_scope"


# --- DEBUG open-admin without keys ---


@pytest.mark.anyio
async def test_debug_open_admin_denied_by_default(hardening_settings):
    """DEBUG with no keys configured denies unknown keys out of the box."""
    hardening_settings.ENVIRONMENT = "local"
    hardening_settings.DEBUG = True
    hardening_settings.VALID_API_KEYS = ""
    hardening_settings.STATIC_DEV_API_KEYS = ""
    hardening_settings.DEBUG_ALLOW_OPEN_ADMIN = False

    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="some-long-enough-key")

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "invalid_api_key"


@pytest.mark.anyio
async def test_debug_open_admin_explicit_opt_in(hardening_settings):
    """DEBUG_ALLOW_OPEN_ADMIN=true restores the legacy local open mode."""
    hardening_settings.ENVIRONMENT = "local"
    hardening_settings.DEBUG = True
    hardening_settings.VALID_API_KEYS = ""
    hardening_settings.STATIC_DEV_API_KEYS = ""
    hardening_settings.DEBUG_ALLOW_OPEN_ADMIN = True

    context = await get_auth_context(api_key="some-long-enough-key")

    assert context.is_bootstrap_admin is True


@pytest.mark.anyio
async def test_debug_open_admin_never_in_production(hardening_settings):
    """The opt-in flag cannot open admin on production-like environments."""
    hardening_settings.ENVIRONMENT = "production"
    hardening_settings.DEBUG = True
    hardening_settings.VALID_API_KEYS = ""
    hardening_settings.STATIC_DEV_API_KEYS = ""
    hardening_settings.DEBUG_ALLOW_OPEN_ADMIN = True

    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="some-long-enough-key")

    assert exc.value.status_code == 403


# --- Policy fail-closed: empty bundles and unknown cost ---


@pytest.mark.anyio
async def test_empty_bundles_denied_when_flag_on(clean_database, hardening_settings):
    hardening_settings.POLICY_DENY_EMPTY_BUNDLES = True

    evaluation = await evaluate_wallet_policy(
        wallet_id="wallet-with-no-bundles", tool_name="any-tool"
    )

    assert evaluation.allowed is False
    assert evaluation.reason == "policy_no_bundles"


@pytest.mark.anyio
async def test_empty_bundles_allowed_when_flag_off(clean_database, hardening_settings):
    hardening_settings.POLICY_DENY_EMPTY_BUNDLES = False

    evaluation = await evaluate_wallet_policy(
        wallet_id="wallet-with-no-bundles", tool_name="any-tool"
    )

    assert evaluation.allowed is True
    assert evaluation.reason == "allowed"


@pytest.mark.anyio
async def test_unknown_cost_denied_when_flag_on(clean_database, hardening_settings):
    """A daily-capped bundle denies unpriced calls (per-action cap alone is
    covered by test_unknown_cost_per_action_denied_when_flag_on)."""
    hardening_settings.POLICY_DENY_UNKNOWN_COST = True
    await _ensure_wallet("wallet-unknown-cost")
    bundle = await create_policy_bundle(
        PolicyBundleCreate(
            wallet_id="wallet-unknown-cost",
            name="capped",
            daily_spend_limit=100,
        )
    )

    evaluation = await evaluate_wallet_policy(
        wallet_id="wallet-unknown-cost",
        tool_name="any-tool",
        estimated_cost=None,
        daily_spend_used=0,
    )
    assert evaluation.allowed is False
    assert evaluation.reason == "daily_spend_estimate_unknown"
    assert evaluation.policy_id == bundle.policy_id


@pytest.mark.anyio
async def test_unknown_cost_per_action_denied_when_flag_on(
    clean_database, hardening_settings
):
    """The per-action cap alone also fails closed on an unknown estimate."""
    hardening_settings.POLICY_DENY_UNKNOWN_COST = True
    await _ensure_wallet("wallet-per-action-cap")
    await create_policy_bundle(
        PolicyBundleCreate(
            wallet_id="wallet-per-action-cap",
            name="capped",
            max_cost_per_action=10,
        )
    )

    evaluation = await evaluate_wallet_policy(
        wallet_id="wallet-per-action-cap",
        tool_name="any-tool",
        estimated_cost=None,
        daily_spend_used=0,
    )

    assert evaluation.allowed is False
    assert evaluation.reason == "max_cost_estimate_unknown"


@pytest.mark.anyio
async def test_unknown_cost_allowed_when_flag_off(clean_database, hardening_settings):
    hardening_settings.POLICY_DENY_UNKNOWN_COST = False
    await _ensure_wallet("wallet-unknown-cost-off")
    await create_policy_bundle(
        PolicyBundleCreate(
            wallet_id="wallet-unknown-cost-off",
            name="capped",
            daily_spend_limit=100,
            max_cost_per_action=10,
        )
    )

    evaluation = await evaluate_wallet_policy(
        wallet_id="wallet-unknown-cost-off",
        tool_name="any-tool",
        estimated_cost=None,
        daily_spend_used=0,
    )

    assert evaluation.allowed is True


@pytest.mark.anyio
async def test_known_over_limit_still_denied_either_way(
    clean_database, hardening_settings
):
    """The flag only closes the unknown-cost gap, it never weakens known costs."""
    await _ensure_wallet("wallet-over-limit")
    await create_policy_bundle(
        PolicyBundleCreate(
            wallet_id="wallet-over-limit",
            name="capped",
            daily_spend_limit=100,
        )
    )

    for flag in (True, False):
        hardening_settings.POLICY_DENY_UNKNOWN_COST = flag
        evaluation = await evaluate_wallet_policy(
            wallet_id="wallet-over-limit",
            tool_name="any-tool",
            estimated_cost=60,
            daily_spend_used=50,
        )
        assert evaluation.allowed is False
        assert evaluation.reason == "daily_spend_limit_exceeded"
