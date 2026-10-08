"""Adversarial checks for API key and bearer authentication.

Covers invalid bearers, truncated keys, a hash mixed with the wrong pepper,
revoked and expired keys, suspended or disabled key status, equal-length
wrong keys, and a revocation that lands after the key row is read.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_auth_context
from app.core.config import get_settings
from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import APIKeyModel, WalletModel
from app.main import app
from app.services import api_key_service as api_key_service_module
from app.services.api_key_service import APIKeyService
from tests.conftest import interleaving_factory
from tests.test_trust_helpers import provision_agent_wallet

# Mount JWT and billing routes for this module without flipping proof surfaces.
pytestmark = pytest.mark.dormant

# 32 raw bytes, strict base64. Same non-secret material the other JWT tests use.
TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="
PEPPER = "pepper-this-process-does-not-use"
SECRET = "b2a_break-auth-secret-value"
PREFIX_LEN = api_key_service_module.API_KEY_PREFIX_LENGTH


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("TRUST_SIGNING_PRIVATE_KEY_B64", TEST_SIGNING_KEY)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


async def _seed_key(
    *,
    wallet_id: str,
    key_id: str,
    secret: str,
    status: str = "active",
    expires_at=None,
    max_uses: int | None = None,
    wallet_status: str = "active",
    key_hash: str | None = None,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            WalletModel(
                wallet_id=wallet_id,
                wallet_type="agent",
                status=wallet_status,
            )
        )
        await session.commit()
        session.add(
            APIKeyModel(
                key_id=key_id,
                wallet_id=wallet_id,
                key_hash=key_hash if key_hash is not None else _digest(secret),
                key_prefix=secret[:PREFIX_LEN],
                status=status,
                expires_at=expires_at,
                max_uses=max_uses,
            )
        )
        await session.commit()


async def _key_row(key_id: str) -> APIKeyModel | None:
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(APIKeyModel, key_id)


@pytest.mark.anyio
async def test_invalid_bearer_does_not_fall_through_to_a_valid_api_key(
    client, clean_database
):
    """A bad Authorization header must not authenticate as X-API-Key."""
    bad_headers = [
        {"Authorization": "Bearer not-a-jwt", "X-API-Key": "test-key"},
        {"Authorization": "Bearer", "X-API-Key": "test-key"},
        {"Authorization": "bearer test-key", "X-API-Key": "test-key"},
        {"Authorization": "Bearer  test-key", "X-API-Key": "test-key"},
        {"Authorization": "Bearer test-key ", "X-API-Key": "test-key"},
        {"Authorization": "Basic test-key", "X-API-Key": "test-key"},
        {"Authorization": "Bearer test-key"},
    ]
    for headers in bad_headers:
        resp = await client.get("/v1/billing/pricing", headers=headers)
        assert resp.status_code == 401, (headers, resp.status_code, resp.text)

    ok = await client.get("/v1/billing/pricing", headers={"X-API-Key": "test-key"})
    assert ok.status_code == 200, ok.text


@pytest.mark.anyio
async def test_equal_length_wrong_env_key_is_rejected_via_compare_digest(
    monkeypatch,
):
    """A wrong key the same length as a configured key must not match."""
    valid = "test-key"
    wrong = "test-kez"
    assert len(valid) == len(wrong)
    seen: list[tuple[str, str, bool]] = []
    real = api_key_service_module.hmac.compare_digest

    def spy(left: str, right: str) -> bool:
        match = real(left, right)
        seen.append((left, right, match))
        return match

    # get_auth_context compares configured keys with this module's hmac.
    from app.core import auth as auth_module

    monkeypatch.setattr(auth_module.hmac, "compare_digest", spy)

    context = await get_auth_context(api_key=valid)
    assert context.is_bootstrap_admin is True

    with pytest.raises(HTTPException) as raised:
        await get_auth_context(api_key=wrong)
    assert raised.value.status_code == 403
    assert raised.value.detail["error"] == "invalid_api_key"
    equal_length_misses = [
        item for item in seen if len(item[0]) == len(item[1]) and item[2] is False
    ]
    assert equal_length_misses
    assert all(item[0] != item[1] for item in equal_length_misses)


@pytest.mark.anyio
async def test_truncated_and_equal_length_wrong_db_keys_are_rejected(
    clean_database,
):
    secret = SECRET
    await _seed_key(wallet_id="agt-trunc", key_id="key-trunc", secret=secret)
    service = APIKeyService()

    assert (await service.validate_key(secret)) is not None
    assert await service.validate_key(secret[:PREFIX_LEN]) is None
    assert await service.validate_key(secret[:-1]) is None
    flipped = f"{secret[:-1]}{'x' if secret[-1] != 'x' else 'y'}"
    assert len(flipped) == len(secret)
    assert await service.validate_key(flipped) is None
    assert await service.validate_key(secret + "extra") is None
    assert await service.validate_key("b2a_' OR '1'='1") is None
    assert await service.validate_key("%%%%%%%%") is None
    assert await service.validate_key("b2a_sec\x00ret-value") is None


@pytest.mark.anyio
async def test_key_hashed_with_a_different_pepper_is_rejected(clean_database):
    """The stored digest is sha256 of the raw key, not sha256 of pepper plus key.

    A row written with some other pepper must not authenticate as that key.
    """
    secret = "b2a_pepper-mismatch-secret"
    peppered = hashlib.sha256((PEPPER + secret).encode()).hexdigest()
    assert peppered != _digest(secret)
    await _seed_key(
        wallet_id="agt-pepper",
        key_id="key-pepper",
        secret=secret,
        key_hash=peppered,
    )
    service = APIKeyService()
    assert await service.validate_key(secret) is None
    assert await service.validate_key(PEPPER + secret) is None


@pytest.mark.anyio
async def test_revoked_expired_suspended_and_disabled_keys_are_rejected(
    clean_database,
):
    service = APIKeyService()
    cases = [
        ("agt-revoked", "key-revoked", "b2a_revoked-key-secret-value", "revoked", None),
        (
            "agt-expired",
            "key-expired",
            "b2a_expired-key-secret-value",
            "active",
            utc_now() - timedelta(seconds=1),
        ),
        (
            "agt-suspended-key",
            "key-suspended",
            "b2a_suspended-key-secret-val",
            "suspended",
            None,
        ),
        (
            "agt-disabled-key",
            "key-disabled",
            "b2a_disabled-key-secret-value",
            "disabled",
            None,
        ),
    ]
    for wallet_id, key_id, secret, status, expires_at in cases:
        await _seed_key(
            wallet_id=wallet_id,
            key_id=key_id,
            secret=secret,
            status=status,
            expires_at=expires_at,
        )
        assert await service.validate_key(secret) is None

    live_until = utc_now() + timedelta(days=1)
    await _seed_key(
        wallet_id="agt-not-yet",
        key_id="key-not-yet",
        secret="b2a_not-yet-expired-secret",
        expires_at=live_until,
    )
    assert (await service.validate_key("b2a_not-yet-expired-secret")) is not None


@pytest.mark.anyio
@pytest.mark.parametrize("wallet_status", ["suspended", "frozen", "closed", "disabled"])
async def test_non_spendable_wallet_key_still_reaches_auth(
    clean_database, wallet_status
):
    """Wallet suspension is a spend control. The key itself still authenticates.

    Invoke and debit tests depend on that: a frozen wallet's own key must reach
    the handler so the denial can be recorded as wallet_frozen, not as a bad key.
    """
    secret = f"b2a_wallet-{wallet_status}-secret"
    await _seed_key(
        wallet_id=f"agt-wallet-{wallet_status}",
        key_id=f"key-wallet-{wallet_status}",
        secret=secret,
        wallet_status=wallet_status,
    )
    accepted = await APIKeyService().validate_key(secret)
    assert accepted is not None
    assert accepted.wallet_id == f"agt-wallet-{wallet_status}"


@pytest.mark.anyio
async def test_unlimited_key_revoked_after_read_is_not_accepted(
    clean_database,
):
    """A revoke that commits after the read must still fail authentication.

    Unlimited keys stamped last_used_at from the row they had already loaded.
    The write did not require the row to still be active, so the request
    authenticated after the key was revoked.
    """
    secret = "b2a_unlimited-revoke-race-secret"
    key_id = "key-unlimited-revoke-race"
    await _seed_key(wallet_id="agt-unlimited-revoke", key_id=key_id, secret=secret)

    service = APIKeyService()
    real_factory = get_session_factory()
    state: dict = {}

    async def _revoke() -> None:
        async with real_factory() as session:
            async with session.begin():
                row = await session.get(APIKeyModel, key_id)
                assert row is not None
                assert row.status == "active"
                row.status = "revoked"
                row.revoked_at = utc_now()
                session.add(row)

    service._session_factory = interleaving_factory(
        real_factory, _revoke, state, fire_on=1
    )

    accepted = await service.validate_key(secret)

    assert state.get("fired") is True
    assert accepted is None
    row = await _key_row(key_id)
    assert row is not None
    assert row.status == "revoked"


@pytest.mark.anyio
async def test_unlimited_key_expired_after_read_is_not_accepted(
    clean_database,
):
    """An expiry written after the read must not still authenticate."""
    secret = "b2a_unlimited-expiry-race-secret"
    key_id = "key-unlimited-expiry-race"
    await _seed_key(wallet_id="agt-unlimited-expiry", key_id=key_id, secret=secret)

    service = APIKeyService()
    real_factory = get_session_factory()
    state: dict = {}

    async def _expire() -> None:
        async with real_factory() as session:
            async with session.begin():
                row = await session.get(APIKeyModel, key_id)
                assert row is not None
                row.expires_at = utc_now() - timedelta(seconds=5)
                session.add(row)

    service._session_factory = interleaving_factory(
        real_factory, _expire, state, fire_on=1
    )

    accepted = await service.validate_key(secret)

    assert state.get("fired") is True
    assert accepted is None


@pytest.mark.anyio
async def test_capped_key_expired_after_read_is_not_accepted(
    clean_database,
):
    """A use budget must not skip the expiry check on the write.

    Keys with max_uses already rechecked status and remaining uses in SQL.
    They did not recheck expires_at, so an expiry committed after the read
    still counted as a successful use.
    """
    secret = "b2a_capped-expiry-race-secret"
    key_id = "key-capped-expiry-race"
    await _seed_key(
        wallet_id="agt-capped-expiry",
        key_id=key_id,
        secret=secret,
        max_uses=3,
    )

    service = APIKeyService()
    real_factory = get_session_factory()
    state: dict = {}

    async def _expire() -> None:
        async with real_factory() as session:
            async with session.begin():
                row = await session.get(APIKeyModel, key_id)
                assert row is not None
                row.expires_at = utc_now() - timedelta(seconds=5)
                session.add(row)

    service._session_factory = interleaving_factory(
        real_factory, _expire, state, fire_on=1
    )

    accepted = await service.validate_key(secret)

    assert state.get("fired") is True
    assert accepted is None
    row = await _key_row(key_id)
    assert row is not None
    assert row.use_count == 0


@pytest.mark.anyio
async def test_unlimited_key_does_not_spend_a_use_and_capped_key_does(
    clean_database,
):
    """The shared write must keep the old budget rules."""
    unlimited = "b2a_unlimited-budget-secret"
    unlimited_id = "key-unlimited-budget"
    await _seed_key(
        wallet_id="agt-unlimited-budget",
        key_id=unlimited_id,
        secret=unlimited,
    )
    service = APIKeyService()
    assert await service.validate_key(unlimited) is not None
    row = await _key_row(unlimited_id)
    assert row is not None
    assert row.use_count == 0
    assert row.last_used_at is not None

    capped = "b2a_capped-budget-secret-val"
    capped_id = "key-capped-budget"
    await _seed_key(
        wallet_id="agt-capped-budget",
        key_id=capped_id,
        secret=capped,
        max_uses=1,
    )
    assert await service.validate_key(capped) is not None
    assert await service.validate_key(capped) is None
    row = await _key_row(capped_id)
    assert row is not None
    assert row.use_count == 1


@pytest.mark.anyio
async def test_malformed_token_exchange_is_rejected(
    client, clean_database, signing_key
):
    payloads = [
        {"json": {"api_key": "short"}},
        {"json": {"api_key": None}},
        {"json": {}},
        {"json": {"api_key": "b2a_long-enough", "scopes": "admin"}},
        {"json": {"api_key": ["b2a_long-enough"]}},
        {"content": b"not-json", "headers": {"content-type": "application/json"}},
    ]
    for payload in payloads:
        resp = await client.post("/v1/auth/token", **payload)
        assert resp.status_code == 422, (payload, resp.status_code, resp.text)


@pytest.mark.anyio
async def test_self_selected_scopes_do_not_become_bootstrap_admin(
    client, clean_database, signing_key
):
    provisioned = await provision_agent_wallet(client)
    exchanged = await client.post(
        "/v1/auth/token",
        json={
            "api_key": provisioned["agent_headers"]["X-API-Key"],
            "scopes": ["admin", "bootstrap", "billing:charge"],
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    minted = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Escalation",
            "email": "escalate@example.test",
            "initial_credits": 1,
        },
        headers={"Authorization": "Bearer " + exchanged.json()["access_token"]},
    )
    assert minted.status_code == 403, minted.text
    assert minted.json()["detail"]["error"] == "admin_access_denied"


@pytest.mark.anyio
async def test_truncated_and_reused_bearer_tokens_are_rejected(
    client, clean_database, signing_key
):
    provisioned = await provision_agent_wallet(client)
    api_key = provisioned["agent_headers"]["X-API-Key"]
    exchanged = await client.post("/v1/auth/token", json={"api_key": api_key})
    assert exchanged.status_code == 200, exchanged.text
    access = exchanged.json()["access_token"]
    refresh = exchanged.json()["refresh_token"]

    truncated = await client.get(
        "/v1/billing/pricing",
        headers={"Authorization": "Bearer " + access[:-8]},
    )
    assert truncated.status_code == 401, truncated.text

    flipped = access[:-1] + ("A" if access[-1] != "A" else "B")
    assert len(flipped) == len(access)
    forged = await client.get(
        "/v1/billing/pricing",
        headers={"Authorization": "Bearer " + flipped},
    )
    assert forged.status_code == 401, forged.text

    as_access = await client.get(
        "/v1/billing/pricing",
        headers={"Authorization": "Bearer " + refresh},
    )
    assert as_access.status_code == 401, as_access.text

    refreshed = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 200, refreshed.text
    replay = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert replay.status_code == 401, replay.text
    assert replay.json()["detail"]["error"] == "revoked_refresh_token"


@pytest.mark.anyio
async def test_suspended_key_cannot_refresh_or_call(
    client, clean_database, signing_key
):
    provisioned = await provision_agent_wallet(client)
    api_key = provisioned["agent_headers"]["X-API-Key"]
    exchanged = await client.post("/v1/auth/token", json={"api_key": api_key})
    assert exchanged.status_code == 200, exchanged.text

    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(APIKeyModel, provisioned["key_id"])
        assert row is not None
        row.status = "suspended"
        session.add(row)
        await session.commit()

    raw = await client.get("/v1/billing/pricing", headers={"X-API-Key": api_key})
    assert raw.status_code == 403, raw.text
    bearer = await client.get(
        "/v1/billing/pricing",
        headers={"Authorization": "Bearer " + exchanged.json()["access_token"]},
    )
    assert bearer.status_code == 401, bearer.text
    refreshed = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": exchanged.json()["refresh_token"]},
    )
    assert refreshed.status_code == 401, refreshed.text
