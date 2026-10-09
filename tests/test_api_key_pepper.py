"""Server pepper for API key digests (defense in depth).

API keys are long random strings, so offline brute force of an unsalted
SHA-256 digest is already impractical; the pepper means a stolen database
dump alone is not enough to test candidate keys. New rows store
HMAC-SHA256 keyed by the API_KEY_PEPPER env var, while rows written before
the pepper was configured keep validating without a data migration.
"""

import hashlib
import hmac

from app.db.database import get_session_factory
from app.db.models import APIKeyModel, WalletModel
from app.services import api_key_service as api_key_service_module
from app.services.api_key_service import APIKeyService


def _peppered_digest(raw_key: str, pepper: bytes) -> str:
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def test_pepper_changes_stored_digest(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_PEPPER", "test-pepper-value")
    full_key, digest, _ = api_key_service_module.generate_api_key()
    assert digest == _peppered_digest(full_key, b"test-pepper-value")
    assert digest != hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def test_no_pepper_keeps_legacy_digest(monkeypatch) -> None:
    monkeypatch.delenv("API_KEY_PEPPER", raising=False)
    full_key, digest, _ = api_key_service_module.generate_api_key()
    assert digest == hashlib.sha256(full_key.encode("utf-8")).hexdigest()


async def _seed_key(wallet_id: str, key_id: str, raw_key: str, digest: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(WalletModel(wallet_id=wallet_id, wallet_type="agent"))
        await session.commit()
        session.add(
            APIKeyModel(
                key_id=key_id,
                wallet_id=wallet_id,
                key_hash=digest,
                key_prefix=raw_key[: api_key_service_module.API_KEY_PREFIX_LENGTH],
            )
        )
        await session.commit()


async def test_peppered_row_validates(clean_database, monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_PEPPER", "test-pepper-value")
    raw_key = "b2a_peppered-test-secret-key"
    await _seed_key(
        "agt-pepper",
        "key-pepper",
        raw_key,
        _peppered_digest(raw_key, b"test-pepper-value"),
    )
    key = await APIKeyService().validate_key(raw_key)
    assert key is not None
    assert key.key_id == "key-pepper"


async def test_legacy_row_still_validates_with_pepper(
    clean_database, monkeypatch
) -> None:
    monkeypatch.setenv("API_KEY_PEPPER", "test-pepper-value")
    raw_key = "b2a_legacy-test-secret-key1"
    await _seed_key(
        "agt-legacy",
        "key-legacy",
        raw_key,
        hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
    )
    key = await APIKeyService().validate_key(raw_key)
    assert key is not None
    assert key.key_id == "key-legacy"


async def test_wrong_key_rejected_with_pepper(clean_database, monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_PEPPER", "test-pepper-value")
    raw_key = "b2a_peppered-test-secret-key"
    await _seed_key(
        "agt-pepper-reject",
        "key-pepper-reject",
        raw_key,
        _peppered_digest(raw_key, b"test-pepper-value"),
    )
    assert await APIKeyService().validate_key(f"{raw_key}x") is None
    assert await APIKeyService().validate_key("b2a_never-issued-secret") is None
