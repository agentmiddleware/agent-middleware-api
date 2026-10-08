"""Unit tests for the shared wrapper permit cache."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from b2a_sdk.errors import AuthorizationError, PermitDeniedError
from b2a_sdk.models import Permit, PermitRequest
from b2a_sdk.permit_cache import PermitCache, is_permit_lifecycle_denial


def _request(expires_at: datetime) -> PermitRequest:
    return PermitRequest(
        issuer_wallet_id="wallet-1",
        subject_wallet_id="wallet-1",
        max_credits=Decimal("100"),
        expires_at=expires_at,
        allowed_tools=["partner.search"],
        scopes=["tool:partner.search:invoke", "billing:charge"],
    )


def _permit(expires_at: datetime, **overrides) -> Permit:
    now = datetime.now(timezone.utc)
    fields: dict = {
        "permit_id": "permit-1",
        "issuer_wallet_id": "wallet-1",
        "subject_wallet_id": "wallet-1",
        "subject_key_id": "key-1",
        "scopes": ["tool:partner.search:invoke", "billing:charge"],
        "allowed_tools": ["partner.search"],
        "max_credits": Decimal("100"),
        "spent_credits": Decimal("0"),
        "expires_at": expires_at,
        "nonce": "nonce-1",
        "status": "active",
        "signature": "sig-1",
        "key_id": "key-1",
        "issued_at": now,
        "revoked_at": None,
        "raw": {},
    }
    fields.update(overrides)
    return Permit(**fields)


def test_hit_returns_permit_id():
    cache = PermitCache()
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    cache.store_request("key-1", _request(expires))
    assert cache.store_permit("key-1", _permit(expires)) is True
    assert cache.get_permit_id("key-1") == "permit-1"
    assert cache.get_request("key-1") is not None


def test_expired_entry_is_a_miss():
    now = datetime.now(timezone.utc)
    clock = {"now": now}
    cache = PermitCache(now=lambda: clock["now"])
    cache.store_request("key-1", _request(now + timedelta(minutes=30)))
    assert cache.store_permit("key-1", _permit(now + timedelta(minutes=30))) is True
    assert cache.get_permit_id("key-1") == "permit-1"

    clock["now"] = now + timedelta(minutes=31)
    assert cache.get_permit_id("key-1") is None
    assert cache.get_request("key-1") is None
    assert len(cache) == 0


def test_lru_evicts_oldest_past_maxsize():
    cache = PermitCache(maxsize=2)
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    cache.store_request("key-1", _request(expires))
    cache.store_request("key-2", _request(expires))
    assert cache.get_request("key-1") is not None  # key-1 now most recent
    cache.store_request("key-3", _request(expires))
    assert len(cache) == 2
    assert cache.get_request("key-2") is None  # least recently used is gone
    assert cache.get_request("key-1") is not None
    assert cache.get_request("key-3") is not None


def test_drop_permit_keeps_request_for_stable_replay():
    cache = PermitCache()
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    cache.store_request("key-1", _request(expires))
    assert cache.store_permit("key-1", _permit(expires)) is True
    cache.drop_permit("key-1")
    assert cache.get_permit_id("key-1") is None
    assert cache.get_request("key-1") is not None


def test_store_permit_refuses_dead_permits():
    cache = PermitCache()
    live = datetime.now(timezone.utc) + timedelta(minutes=30)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    cache.store_request("key-1", _request(live))
    assert cache.store_permit("key-1", _permit(live)) is True

    assert cache.store_permit("key-1", _permit(past)) is False
    assert cache.get_permit_id("key-1") is None

    assert cache.store_permit("key-1", _permit(live, status="revoked")) is False
    assert cache.get_permit_id("key-1") is None

    revoked_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert cache.store_permit("key-1", _permit(live, revoked_at=revoked_at)) is False
    assert cache.get_permit_id("key-1") is None


def test_maxsize_must_be_positive():
    with pytest.raises(ValueError):
        PermitCache(maxsize=0)


@pytest.mark.parametrize("reason", ["permit_expired", "permit_revoked"])
def test_lifecycle_denials_detected(reason: str):
    assert is_permit_lifecycle_denial(PermitDeniedError(reason)) is True


@pytest.mark.parametrize("reason", ["permit_not_found", "permit_wallet_mismatch", "other"])
def test_non_lifecycle_denials_ignored(reason: str):
    assert is_permit_lifecycle_denial(PermitDeniedError(reason)) is False


def test_non_permit_errors_ignored():
    assert is_permit_lifecycle_denial(AuthorizationError("nope")) is False
    assert is_permit_lifecycle_denial(ValueError("permit_expired")) is False
