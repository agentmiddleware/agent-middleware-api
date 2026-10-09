"""Focused unit tests for app.db.models table definitions.

Uses an in-memory SQLite database so the tests stay fast and free of
external services. Covers model defaults, table identity, monetary
precision, and two error paths (missing required field, duplicate
idempotency identity).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    BillingAlertModel,
    LedgerEntryModel,
    PermitModel,
    WalletModel,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _wallet(wallet_id="w1", **overrides):
    values = {"wallet_id": wallet_id, "wallet_type": "sponsor"}
    values.update(overrides)
    return WalletModel(**values)


def test_wallet_defaults_use_zero_decimal_and_active_status():
    wallet = _wallet()

    assert wallet.balance == Decimal("0")
    assert wallet.lifetime_credits == Decimal("0")
    assert wallet.lifetime_debits == Decimal("0")
    assert wallet.daily_spent == Decimal("0")
    assert wallet.hourly_spent == Decimal("0")
    assert wallet.status == "active"
    assert wallet.auto_refill is False
    assert wallet.parent_wallet_id is None
    assert wallet.created_at is not None
    assert wallet.updated_at is not None
    assert wallet.created_at.tzinfo is None


def test_core_table_names_are_registered():
    assert WalletModel.__tablename__ == "wallets"
    assert LedgerEntryModel.__tablename__ == "ledger_entries"
    assert BillingAlertModel.__tablename__ == "billing_alerts"
    assert PermitModel.__tablename__ == "permits"
    tables = set(SQLModel.metadata.tables)
    assert {"wallets", "ledger_entries", "billing_alerts", "permits"} <= tables


def test_ledger_entry_defaults_and_sign_convention():
    credit = LedgerEntryModel(
        entry_id="e1",
        wallet_id="w1",
        action="credit",
        amount=Decimal("5"),
        balance_after=Decimal("5"),
    )
    debit = LedgerEntryModel(
        entry_id="e2",
        wallet_id="w1",
        action="debit",
        amount=Decimal("-5"),
        balance_after=Decimal("0"),
    )

    assert credit.description == ""
    assert credit.operation_key is None
    assert credit.amount > 0
    assert debit.amount < 0


def test_billing_alert_defaults():
    alert = BillingAlertModel(
        alert_id="a1", wallet_id="w1", alert_type="low_balance", message="low"
    )

    assert alert.severity == "info"
    assert alert.acknowledged is False
    assert alert.created_at.tzinfo is None


def test_monetary_values_keep_decimal_precision(engine):
    with Session(engine) as session:
        session.add(_wallet(balance=Decimal("10.12345678")))
        session.commit()

    with Session(engine) as session:
        wallet = session.get(WalletModel, "w1")
        assert wallet.balance == Decimal("10.12345678")


def test_aware_datetime_is_stored_as_naive_utc(engine):
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(_wallet(daily_reset_at=aware))
        session.commit()

    with Session(engine) as session:
        wallet = session.get(WalletModel, "w1")
        assert wallet.daily_reset_at == datetime(2026, 1, 2, 3, 4, 5)
        assert wallet.daily_reset_at.tzinfo is None


def test_missing_required_amount_is_rejected_by_the_database(engine):
    # SQLModel table classes do not validate on construction (missing
    # fields become None), so the NOT NULL column is the real guard.
    with Session(engine) as session:
        session.add(_wallet())
        session.add(
            LedgerEntryModel(
                entry_id="e9",
                wallet_id="w1",
                action="debit",
                balance_after=Decimal("9"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_operation_key_for_same_wallet_is_rejected(engine):
    def _entry(entry_id):
        return LedgerEntryModel(
            entry_id=entry_id,
            wallet_id="w1",
            action="debit",
            amount=Decimal("-1"),
            balance_after=Decimal("9"),
            operation_key="op-1",
        )

    with Session(engine) as session:
        session.add(_wallet())
        session.add(_entry("e1"))
        session.commit()

    with Session(engine) as session:
        session.add(_entry("e2"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_same_operation_key_on_different_wallets_is_allowed(engine):
    with Session(engine) as session:
        session.add(_wallet("w1"))
        session.add(_wallet("w2"))
        session.add(
            LedgerEntryModel(
                entry_id="e1",
                wallet_id="w1",
                action="debit",
                amount=Decimal("-1"),
                balance_after=Decimal("9"),
                operation_key="op-shared",
            )
        )
        session.add(
            LedgerEntryModel(
                entry_id="e2",
                wallet_id="w2",
                action="debit",
                amount=Decimal("-1"),
                balance_after=Decimal("9"),
                operation_key="op-shared",
            )
        )
        session.commit()

    with Session(engine) as session:
        rows = session.exec(select(LedgerEntryModel)).all()
        assert len(rows) == 2


def test_permit_unique_constraint_covers_permit_id_and_nonce():
    unique_names = {
        c.name
        for c in PermitModel.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert "uq_permits_permit_nonce" in unique_names
