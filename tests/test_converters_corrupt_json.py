"""Corrupt stored JSON must not read as empty for money records.

Wallet and ledger converters raise a typed error (logged at error level)
on corrupt metadata so bad rows are never mistaken for rows with no
metadata. Non-money converters keep their empty fallbacks but log.
"""

import logging

import pytest

from app.core.blob import get_blob_backend
from app.db.converters import (
    CorruptStoredJsonError,
    ledger_entry_model_to_schema,
    wallet_model_to_response,
)
from app.db.models import LedgerEntryModel, WalletModel


def _wallet(**overrides):
    base = dict(
        wallet_id="w-1",
        wallet_type="sponsor",
        balance=100,
        lifetime_credits=100,
        lifetime_debits=0,
    )
    base.update(overrides)
    return WalletModel(**base)


def _ledger_entry(**overrides):
    base = dict(
        entry_id="e-1",
        wallet_id="w-1",
        action="credit",
        amount=10,
        balance_after=110,
    )
    base.update(overrides)
    return LedgerEntryModel(**base)


def test_wallet_corrupt_metadata_raises_typed_error(caplog):
    wallet = _wallet(metadata_json="{not-json")
    with caplog.at_level(logging.ERROR, logger="app.db.converters"):
        with pytest.raises(CorruptStoredJsonError, match="w-1"):
            wallet_model_to_response(wallet)
    assert any(
        r.levelno == logging.ERROR and "w-1" in r.getMessage() for r in caplog.records
    )


def test_ledger_corrupt_metadata_raises_typed_error(caplog):
    entry = _ledger_entry(metadata_json="{not-json")
    with caplog.at_level(logging.ERROR, logger="app.db.converters"):
        with pytest.raises(CorruptStoredJsonError, match="e-1"):
            ledger_entry_model_to_schema(entry)
    assert any(
        r.levelno == logging.ERROR and "e-1" in r.getMessage() for r in caplog.records
    )


def test_corrupt_error_is_a_value_error():
    assert issubclass(CorruptStoredJsonError, ValueError)


def test_wallet_valid_metadata_still_parses():
    wallet = _wallet(metadata_json='{"tier": "gold"}')
    assert wallet_model_to_response(wallet).metadata == {"tier": "gold"}


def test_ledger_valid_metadata_still_parses():
    entry = _ledger_entry(metadata_json='{"source": "test"}')
    assert ledger_entry_model_to_schema(entry).metadata == {"source": "test"}


def test_unknown_blob_backend_raises_clear_error(monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "moonbase")
    get_blob_backend.cache_clear()
    try:
        with pytest.raises(ValueError, match="Unknown BLOB_BACKEND"):
            get_blob_backend()
    finally:
        get_blob_backend.cache_clear()
