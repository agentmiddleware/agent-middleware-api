"""Tests for the shadow ledger dry-run sandbox (app/services/shadow_ledger.py).

The ledger simulates billing without touching real balances. These tests
drive the in-memory store directly (no Redis, no database), so they stay
fast and hermetic.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.billing import InsufficientFundsResponse, ServiceCategory
from app.services.shadow_ledger import DryRunSession, ShadowLedger


@pytest.fixture
def ledger():
    """A ShadowLedger pinned to its in-memory store whatever the env says."""
    instance = ShadowLedger()
    instance._redis_url = ""
    instance._redis = None
    return instance


class _FakeAgentMoney:
    """Minimal stand-in for AgentMoney: records charges, reports a balance."""

    def __init__(self, balance=Decimal("100"), fail_with_insufficient=False):
        self.charges = []
        self._balance = balance
        self.fail_with_insufficient = fail_with_insufficient

    async def charge(
        self, *, wallet_id, service_category, units, description, dry_run=False
    ):
        self.charges.append(
            {
                "wallet_id": wallet_id,
                "service_category": service_category,
                "units": units,
                "description": description,
                "dry_run": dry_run,
            }
        )
        if self.fail_with_insufficient:
            return InsufficientFundsResponse(
                wallet_id=wallet_id,
                current_balance=float(self._balance),
                required_amount=10.0,
                shortfall=5.0,
                top_up_url="http://test/topup",
            )
        return SimpleNamespace(ok=True)

    async def get_wallet(self, wallet_id):
        return SimpleNamespace(balance=self._balance)


@pytest.mark.anyio
async def test_create_and_get_session_roundtrip(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))

    assert session.session_id
    assert session.wallet_id == "wallet-1"
    assert session.real_balance == Decimal("100")
    assert session.simulated_charges == []

    fetched = await ledger.get_session(session.session_id)
    assert fetched is not None
    assert fetched.session_id == session.session_id
    assert fetched.wallet_id == "wallet-1"
    assert fetched.real_balance == Decimal("100")


@pytest.mark.anyio
async def test_get_unknown_session_returns_none(ledger):
    assert await ledger.get_session("no-such-session") is None


def test_session_balance_properties():
    session = DryRunSession(session_id="s", wallet_id="w", real_balance=Decimal("100"))
    assert session.total_simulated == Decimal("0")
    assert session.virtual_balance == Decimal("100")


@pytest.mark.anyio
async def test_simulate_charge_reduces_virtual_balance(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))

    result = await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=3.0
    )

    # TELEMETRY_PM prices at 1.0 credit per event.
    assert result.would_succeed is True
    assert result.dry_run is True
    assert result.credits_would_charge == Decimal("3.0")
    assert isinstance(result.simulated_balance_before, Decimal)
    assert isinstance(result.simulated_balance_after, Decimal)
    assert result.simulated_balance_before == Decimal("100")
    assert result.simulated_balance_after == Decimal("97.0")
    assert result.charge_id

    fetched = await ledger.get_session(session.session_id)
    assert len(fetched.simulated_charges) == 1
    assert fetched.total_simulated == Decimal("3.0")
    assert fetched.virtual_balance == Decimal("97.0")


@pytest.mark.anyio
async def test_simulate_charge_insufficient_funds_records_nothing(ledger):
    session = await ledger.create_session("wallet-1", Decimal("2"))

    result = await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=5.0
    )

    assert result.would_succeed is False
    assert result.reason == "insufficient_simulated_funds"

    fetched = await ledger.get_session(session.session_id)
    assert fetched.simulated_charges == []
    assert fetched.virtual_balance == Decimal("2")


@pytest.mark.anyio
async def test_simulate_charge_blocked_reason_fails_even_with_funds(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))

    result = await ledger.simulate_charge(
        session.session_id,
        ServiceCategory.TELEMETRY_PM,
        units=1.0,
        blocked_reason="policy_denied",
    )

    assert result.would_succeed is False
    assert result.reason == "policy_denied"

    fetched = await ledger.get_session(session.session_id)
    assert fetched.simulated_charges == []


@pytest.mark.anyio
async def test_simulate_charge_unknown_session_raises(ledger):
    with pytest.raises(ValueError, match="Session not found"):
        await ledger.simulate_charge(
            "no-such-session", ServiceCategory.TELEMETRY_PM, units=1.0
        )


@pytest.mark.anyio
async def test_end_session_returns_summary_and_clears(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))
    await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=3.0
    )

    summary = await ledger.end_session(session.session_id)

    assert summary is not None
    assert summary.charge_count == 1
    assert summary.total_simulated_credits == Decimal("3.0")
    assert summary.real_balance == Decimal("100")
    assert summary.virtual_balance_after == Decimal("97.0")
    assert len(summary.simulated_charges) == 1

    assert await ledger.get_session(session.session_id) is None
    assert await ledger.end_session(session.session_id) is None


@pytest.mark.anyio
async def test_revert_session_discards_without_side_effects(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))
    await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=3.0
    )

    result = await ledger.revert_session(session.session_id)

    assert result.reverted is True
    assert result.wallet_id == "wallet-1"
    assert await ledger.get_session(session.session_id) is None


@pytest.mark.anyio
async def test_revert_unknown_session_reports_not_found(ledger):
    result = await ledger.revert_session("no-such-session")

    assert result.reverted is False
    assert result.message == "Session not found"


@pytest.mark.anyio
async def test_commit_session_applies_charges_and_claims_session(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))
    await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=3.0
    )
    money = _FakeAgentMoney(balance=Decimal("97"))

    result = await ledger.commit_session(session.session_id, money)

    assert result.success is True
    assert result.committed_charges == 1
    assert result.total_credits_deducted == Decimal("3.0")
    assert result.real_balance_before == Decimal("100")
    assert result.real_balance_after == Decimal("97")
    assert len(money.charges) == 1
    assert money.charges[0]["dry_run"] is False
    assert money.charges[0]["description"].startswith("[COMMITTED]")

    # The commit claims the session, so a second commit finds nothing.
    again = await ledger.commit_session(session.session_id, money)
    assert again.success is False
    assert again.message == "Session not found"
    assert len(money.charges) == 1


@pytest.mark.anyio
async def test_commit_empty_session_is_a_noop_success(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))
    money = _FakeAgentMoney()

    result = await ledger.commit_session(session.session_id, money)

    assert result.success is True
    assert result.committed_charges == 0
    assert result.message == "No charges to commit"
    assert money.charges == []


@pytest.mark.anyio
async def test_commit_unknown_session_reports_not_found(ledger):
    result = await ledger.commit_session("no-such-session", _FakeAgentMoney())

    assert result.success is False
    assert result.message == "Session not found"


@pytest.mark.anyio
async def test_commit_records_insufficient_funds_per_charge(ledger):
    session = await ledger.create_session("wallet-1", Decimal("100"))
    await ledger.simulate_charge(
        session.session_id, ServiceCategory.TELEMETRY_PM, units=3.0
    )
    money = _FakeAgentMoney(fail_with_insufficient=True)

    result = await ledger.commit_session(session.session_id, money)

    assert result.success is False
    assert result.committed_charges == 0
    assert len(result.ledger_entries) == 1
    assert result.ledger_entries[0]["committed"] is False


@pytest.mark.anyio
async def test_list_sessions_filters_by_wallet(ledger):
    first = await ledger.create_session("wallet-1", Decimal("100"))
    second = await ledger.create_session("wallet-2", Decimal("50"))

    wallet_one = await ledger.list_sessions("wallet-1")

    assert [s.session_id for s in wallet_one] == [first.session_id]
    assert second.session_id not in [s.session_id for s in wallet_one]
