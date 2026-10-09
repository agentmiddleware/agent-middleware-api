"""Focused service-level coverage for app/services/api_key_service.py.

The existing API-key tests exercise this module through HTTP routes
(tests/test_api_keys.py) or pin one regression
(tests/test_api_key_constant_time.py). These tests call APIKeyService
directly to cover its main public behavior: key generation helpers,
creation, validation (including expiry and use budgets), rotation,
revocation, emergency revocation, and the error cases for each.
"""

import hashlib

import pytest

from app.db.database import get_session_factory
from app.db.models import WalletModel
from app.services.api_key_service import (
    APIKeyService,
    InvalidRotationRequestError,
    KeyNotFoundError,
    WalletNotFoundError,
    generate_api_key,
    mask_key,
)


async def _make_wallet(wallet_id: str = "wlt-key-service-test") -> str:
    factory = get_session_factory()
    async with factory() as session:
        session.add(WalletModel(wallet_id=wallet_id, wallet_type="agent"))
        await session.commit()
    return wallet_id


def _stub_notifications(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    sent: list[dict] = []

    async def _fake_send_security_alert(
        wallet_id: str, alert_type: str, message: str
    ) -> None:
        sent.append(
            {"wallet_id": wallet_id, "alert_type": alert_type, "message": message}
        )

    class _StubNotifications:
        send_security_alert = staticmethod(_fake_send_security_alert)

    monkeypatch.setattr(
        "app.services.notifications.get_notification_service",
        lambda: _StubNotifications(),
    )
    return sent


def test_generate_api_key_shape_and_uniqueness() -> None:
    full_key, key_hash, key_prefix = generate_api_key()
    assert full_key.startswith("b2a_")
    assert key_hash == hashlib.sha256(full_key.encode()).hexdigest()
    assert key_prefix == full_key[:8]

    other_key, _, _ = generate_api_key()
    assert other_key != full_key


def test_mask_key_hides_long_key_and_stars_short_key() -> None:
    full_key, _, _ = generate_api_key()
    masked = mask_key(full_key)
    assert full_key not in masked
    assert masked.startswith(full_key[:6])
    assert masked.endswith(full_key[-4:])

    assert mask_key("short") == "*****"


@pytest.mark.anyio
async def test_create_key_returns_usable_credential(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    created = await service.create_key(wallet_id, key_name="ops")
    assert created["wallet_id"] == wallet_id
    assert created["api_key"].startswith("b2a_")
    assert created["status"] == "active"
    assert created["key_name"] == "ops"

    validated = await service.validate_key(created["api_key"])
    assert validated is not None
    assert validated.key_id == created["key_id"]


@pytest.mark.anyio
async def test_create_key_unknown_wallet_raises(clean_database) -> None:
    with pytest.raises(WalletNotFoundError):
        await APIKeyService().create_key("wlt-does-not-exist")


@pytest.mark.anyio
async def test_validate_key_rejects_short_and_unknown_keys(clean_database) -> None:
    service = APIKeyService()
    assert await service.validate_key("") is None
    assert await service.validate_key("short") is None

    full_key, _, _ = generate_api_key()
    assert await service.validate_key(full_key) is None


@pytest.mark.anyio
async def test_validate_key_rejects_expired_key(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    created = await service.create_key(wallet_id, expires_in_days=-1)
    assert await service.validate_key(created["api_key"]) is None
    assert await service.is_key_live(created["key_id"]) is False


@pytest.mark.anyio
async def test_validate_key_enforces_max_uses(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    created = await service.create_key(wallet_id, max_uses=1)
    assert await service.validate_key(created["api_key"]) is not None
    assert await service.validate_key(created["api_key"]) is None


@pytest.mark.anyio
async def test_get_keys_masks_material_and_counts_states(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    first = await service.create_key(wallet_id, key_name="one")
    second = await service.create_key(wallet_id, key_name="two")
    await service.revoke_key(wallet_id, first["key_id"])

    listing = await service.get_keys(wallet_id)
    assert listing["wallet_id"] == wallet_id
    assert listing["total_active"] == 1
    assert listing["total_revoked"] == 1
    for entry in listing["keys"]:
        assert "api_key" not in entry
        assert first["api_key"] not in str(entry)
        assert second["api_key"] not in str(entry)


@pytest.mark.anyio
async def test_revoke_unknown_key_raises(clean_database) -> None:
    wallet_id = await _make_wallet()
    with pytest.raises(KeyNotFoundError):
        await APIKeyService().revoke_key(wallet_id, "key-does-not-exist")


@pytest.mark.anyio
async def test_rotate_key_revokes_old_and_issues_new(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    old = await service.create_key(wallet_id)
    rotation = await service.rotate_key(
        wallet_id, key_id=old["key_id"], revoke_old=True
    )

    assert rotation["old_key_id"] == old["key_id"]
    assert rotation["revoked_keys"] == [old["key_id"]]
    assert rotation["new_key"] is not None
    assert rotation["new_key"]["api_key"] != old["api_key"]
    assert await service.validate_key(old["api_key"]) is None
    assert await service.validate_key(rotation["new_key"]["api_key"]) is not None


@pytest.mark.anyio
async def test_rotate_revoke_old_without_key_id_raises(clean_database) -> None:
    wallet_id = await _make_wallet()
    with pytest.raises(InvalidRotationRequestError):
        await APIKeyService().rotate_key(wallet_id, revoke_old=True)


@pytest.mark.anyio
async def test_rotate_capped_key_without_revoke_old_raises(
    clean_database,
) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    capped = await service.create_key(wallet_id, max_uses=3)
    with pytest.raises(InvalidRotationRequestError):
        await service.rotate_key(wallet_id, key_id=capped["key_id"], revoke_old=False)


@pytest.mark.anyio
async def test_auto_rotate_contained_to_live_key(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    old = await service.create_key(wallet_id)
    result = await service.auto_rotate_on_suspicious_activity(
        wallet_id, reason="test-signal"
    )

    assert result["rotation_type"] == "automatic"
    assert result["old_key_id"] == old["key_id"]
    assert await service.validate_key(old["api_key"]) is None
    assert result["new_key"] is not None
    assert await service.validate_key(result["new_key"]["api_key"]) is not None


@pytest.mark.anyio
async def test_auto_rotate_without_live_key_raises(clean_database) -> None:
    wallet_id = await _make_wallet("wlt-key-service-empty")
    with pytest.raises(InvalidRotationRequestError):
        await APIKeyService().auto_rotate_on_suspicious_activity(
            wallet_id, reason="test-signal"
        )


@pytest.mark.anyio
async def test_emergency_revocation_replaces_all_keys(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _stub_notifications(monkeypatch)
    wallet_id = await _make_wallet()
    service = APIKeyService()

    first = await service.create_key(wallet_id)
    second = await service.create_key(wallet_id)

    result = await service.emergency_revocation(wallet_id, reason="test-incident")

    assert sorted(result["revoked_keys"]) == sorted([first["key_id"], second["key_id"]])
    assert await service.validate_key(first["api_key"]) is None
    assert await service.validate_key(second["api_key"]) is None
    assert result["new_key"] is not None
    assert await service.validate_key(result["new_key"]["api_key"]) is not None
    assert sent and sent[0]["wallet_id"] == wallet_id

    logs = await service.get_rotation_logs(wallet_id)
    assert any(entry["rotation_type"] == "emergency" for entry in logs)


@pytest.mark.anyio
async def test_consume_derived_key_use_spends_budget(clean_database) -> None:
    wallet_id = await _make_wallet()
    service = APIKeyService()

    created = await service.create_key(wallet_id, max_uses=2)
    assert await service.consume_derived_key_use(created["key_id"], wallet_id) is True
    assert await service.consume_derived_key_use(created["key_id"], wallet_id) is True
    assert await service.consume_derived_key_use(created["key_id"], wallet_id) is False
    assert await service.is_key_bounded(created["key_id"]) is True
    assert await service.is_key_bounded(None) is True
