"""Focused regression coverage for DB-backed API-key digest comparison."""

import hashlib

import pytest

from app.db.database import get_session_factory
from app.db.models import APIKeyModel, WalletModel
from app.services import api_key_service as api_key_service_module
from app.services.api_key_service import APIKeyService


VALID_API_KEY = "b2a_same-prefix-authenticated-secret"
NEAR_MISS_API_KEY = f"{VALID_API_KEY[:-1]}x"


@pytest.mark.anyio
async def test_db_key_digest_comparison_is_constant_time_for_valid_and_near_miss(
    clean_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    valid_hash = hashlib.sha256(VALID_API_KEY.encode()).hexdigest()
    near_miss_hash = hashlib.sha256(NEAR_MISS_API_KEY.encode()).hexdigest()
    assert (
        VALID_API_KEY[: api_key_service_module.API_KEY_PREFIX_LENGTH]
        == NEAR_MISS_API_KEY[: api_key_service_module.API_KEY_PREFIX_LENGTH]
    )

    factory = get_session_factory()
    async with factory() as session:
        session.add(
            WalletModel(
                wallet_id="agt-constant-time-key",
                wallet_type="agent",
            )
        )
        await session.commit()
        session.add(
            APIKeyModel(
                key_id="key-constant-time",
                wallet_id="agt-constant-time-key",
                key_hash=valid_hash,
                key_prefix=VALID_API_KEY[
                    : api_key_service_module.API_KEY_PREFIX_LENGTH
                ],
            )
        )
        await session.commit()

    comparisons: list[tuple[str, str]] = []
    real_compare_digest = api_key_service_module.hmac.compare_digest

    def record_compare_digest(stored_digest: str, supplied_digest: str) -> bool:
        comparisons.append((stored_digest, supplied_digest))
        return real_compare_digest(stored_digest, supplied_digest)

    monkeypatch.setattr(
        api_key_service_module.hmac,
        "compare_digest",
        record_compare_digest,
    )

    service = APIKeyService()
    valid = await service.validate_key(VALID_API_KEY)
    near_miss = await service.validate_key(NEAR_MISS_API_KEY)

    assert valid is not None
    assert valid.key_id == "key-constant-time"
    assert near_miss is None
    assert comparisons == [
        (valid_hash, valid_hash),
        (valid_hash, near_miss_hash),
    ]
    assert all(
        len(digest) == hashlib.sha256().digest_size * 2
        for comparison in comparisons
        for digest in comparison
    )
