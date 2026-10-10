"""Peppered API key hashes: new keys use HMAC, legacy hashes keep working."""

import hashlib
import hmac as hmac_stdlib
from types import SimpleNamespace

import pytest

from app.db.database import get_session_factory
from app.db.models import APIKeyModel, WalletModel
from app.services import api_key_service as api_key_service_module
from app.services.api_key_service import APIKeyService

PEPPER = "test-pepper-value-never-used-in-prod"


def _use_pepper(monkeypatch: pytest.MonkeyPatch, pepper: str = PEPPER) -> None:
    monkeypatch.setattr(
        api_key_service_module,
        "get_settings",
        lambda: SimpleNamespace(API_KEY_PEPPER=pepper),
    )


def _plain_digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _peppered_digest(key: str) -> str:
    return hmac_stdlib.new(PEPPER.encode(), key.encode(), hashlib.sha256).hexdigest()


async def _store_key(key_id: str, wallet_id: str, full_key: str, digest: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(WalletModel(wallet_id=wallet_id, wallet_type="agent"))
        await session.commit()
        session.add(
            APIKeyModel(
                key_id=key_id,
                wallet_id=wallet_id,
                key_hash=digest,
                key_prefix=full_key[: api_key_service_module.API_KEY_PREFIX_LENGTH],
            )
        )
        await session.commit()


@pytest.mark.anyio
async def test_new_key_uses_pepper_when_configured(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pepper(monkeypatch)
    full_key, digest, _prefix = api_key_service_module.generate_api_key()
    assert digest == _peppered_digest(full_key)
    assert digest != _plain_digest(full_key)


@pytest.mark.anyio
async def test_new_key_uses_plain_hash_without_pepper(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pepper(monkeypatch, pepper="")
    full_key, digest, _prefix = api_key_service_module.generate_api_key()
    assert digest == _plain_digest(full_key)


@pytest.mark.anyio
async def test_legacy_unpeppered_hash_still_verifies(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pepper(monkeypatch)
    full_key = "b2a_legacy-key-pepper-test-0001"
    await _store_key(
        "key-pepper-legacy", "agt-pepper-legacy", full_key, _plain_digest(full_key)
    )
    found = await APIKeyService().validate_key(full_key)
    assert found is not None
    assert found.key_id == "key-pepper-legacy"


@pytest.mark.anyio
async def test_peppered_hash_verifies(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pepper(monkeypatch)
    full_key, digest, _prefix = api_key_service_module.generate_api_key()
    await _store_key("key-pepper-new", "agt-pepper-new", full_key, digest)
    found = await APIKeyService().validate_key(full_key)
    assert found is not None
    assert found.key_id == "key-pepper-new"


@pytest.mark.anyio
async def test_wrong_key_fails_with_pepper_configured(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pepper(monkeypatch)
    full_key, digest, _prefix = api_key_service_module.generate_api_key()
    await _store_key("key-pepper-wrong", "agt-pepper-wrong", full_key, digest)
    service = APIKeyService()
    assert await service.validate_key("b2a_tampered-key-pepper-0002") is None
    assert await service.validate_key(full_key) is not None
