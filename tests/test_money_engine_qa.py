"""Deep QA for the money engines: wallet lifecycle, transfers, charges.

Service-level tests over wallet_engine.py and agent_money.py, plus
test-only coverage of billing_engine.py (in-flight, no product edits).
Uses the shared ``clean_database`` fixture and ``get_agent_money()``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, LedgerEntryModel, WalletModel
from app.schemas.billing import ServiceCategory
from app.services.agent_money import (
    InsufficientFundsError,
    WalletNotFoundError,
    get_agent_money,
)
from app.services.billing_engine import (
    DirectTopUpDisabledError,
    LedgerOperationConflictError,
)

PLATFORM_FEE = ServiceCategory.PLATFORM_FEE


@pytest.fixture
async def money(clean_database):
    return get_agent_money()


@pytest.fixture
async def sponsor(money):
    return await money.create_sponsor_wallet(
        "QA Sponsor", "qa@example.test", Decimal("10000")
    )


@pytest.fixture
async def agent_pair(money, sponsor):
    first = await money.create_agent_wallet(
        sponsor.wallet_id, "qa-agent-1", Decimal("1000")
    )
    second = await money.create_agent_wallet(
        sponsor.wallet_id, "qa-agent-2", Decimal("100")
    )
    return first, second


async def _stored_balance(wallet_id: str) -> Decimal:
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _stored_status(wallet_id: str) -> str:
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.status


async def _set_status(wallet_id: str, status: str) -> None:
    async with get_session_factory()() as session:
        async with session.begin():
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            wallet.status = status


async def _wallet_count() -> int:
    from sqlalchemy import func, select

    async with get_session_factory()() as session:
        return await session.scalar(select(func.count()).select_from(WalletModel))


def _charge_amount(money, units: Decimal) -> Decimal:
    price = next(
        p for p in money.get_pricing_table() if p.service_category == PLATFORM_FEE
    )
    return units * Decimal(price.credits_per_unit_exact)


# --- Sponsor creation -------------------------------------------------------


async def test_sponsor_negative_initial_credits_rejected(money):
    """A negative opening balance must never create a liability wallet."""
    before = await _wallet_count()
    with pytest.raises(ValueError, match="initial_credits"):
        await money.create_sponsor_wallet("Neg", "neg@example.test", Decimal("-1"))
    assert await _wallet_count() == before


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
async def test_sponsor_nonfinite_initial_credits_rejected(money, bad):
    """NaN/Infinity openings must not reach the database as balances."""
    before = await _wallet_count()
    with pytest.raises(ValueError, match="initial_credits"):
        await money.create_sponsor_wallet("Bad", "bad@example.test", bad)
    assert await _wallet_count() == before


async def test_sponsor_opening_deposit_matches_ledger(money):
    wallet = await money.create_sponsor_wallet(
        "Funded", "funded@example.test", Decimal("250")
    )
    entries = await money.get_ledger(wallet.wallet_id)
    assert len(entries) == 1
    assert entries[0].action.value == "credit"
    assert Decimal(entries[0].amount_exact) == Decimal("250")
    assert Decimal(entries[0].balance_after_exact) == Decimal("250")


# --- Agent provisioning -----------------------------------------------------


async def test_agent_negative_budget_rejected(money, sponsor):
    with pytest.raises(ValueError, match="budget_credits"):
        await money.create_agent_wallet(sponsor.wallet_id, "neg", Decimal("-5"))


async def test_agent_zero_budget_opens_empty_wallet_without_moving_funds(
    money, sponsor
):
    before = await _stored_balance(sponsor.wallet_id)
    wallet = await money.create_agent_wallet(sponsor.wallet_id, "zero", Decimal("0"))
    assert wallet.balance == 0
    assert await _stored_balance(sponsor.wallet_id) == before


async def test_agent_from_missing_sponsor_raises(money):
    with pytest.raises(WalletNotFoundError):
        await money.create_agent_wallet("spn-missing", "ghost", Decimal("10"))


async def test_agent_from_non_sponsor_rejected(money, sponsor, agent_pair):
    agent = agent_pair[0]
    with pytest.raises(ValueError, match="sponsor"):
        await money.create_agent_wallet(agent.wallet_id, "nested", Decimal("10"))


async def test_agent_over_sponsor_balance_reports_shortfall(money, sponsor):
    with pytest.raises(InsufficientFundsError) as exc_info:
        await money.create_agent_wallet(sponsor.wallet_id, "rich", Decimal("999999"))
    assert exc_info.value.shortfall == Decimal("999999") - Decimal("10000")


# --- Child wallets ----------------------------------------------------------


async def test_child_negative_budget_rejected(money, agent_pair):
    with pytest.raises(ValueError, match="budget_credits"):
        await money.create_child_wallet(
            agent_pair[0].wallet_id, "neg-child", Decimal("-5"), Decimal("10")
        )


@pytest.mark.parametrize("bad_ttl", [0, -30, True, 2_147_483_648])
async def test_child_bad_ttl_rejected(money, agent_pair, bad_ttl):
    with pytest.raises(ValueError, match="ttl_seconds"):
        await money.create_child_wallet(
            agent_pair[0].wallet_id,
            "ttl-child",
            Decimal("10"),
            Decimal("10"),
            ttl_seconds=bad_ttl,
        )


async def test_child_from_sponsor_rejected(money, sponsor):
    with pytest.raises(ValueError, match="Only agent or child"):
        await money.create_child_wallet(
            sponsor.wallet_id, "direct", Decimal("10"), Decimal("10")
        )


async def test_nested_child_past_parent_cap_rejected(money, agent_pair):
    child = await money.create_child_wallet(
        agent_pair[0].wallet_id, "cap-child", Decimal("100"), Decimal("50")
    )
    with pytest.raises(ValueError, match="spend cap"):
        await money.create_child_wallet(
            child.wallet_id, "grandchild", Decimal("60"), Decimal("60")
        )


async def test_child_delegation_conserves_funds(money, agent_pair):
    parent_id = agent_pair[0].wallet_id
    before = await _stored_balance(parent_id)
    child = await money.create_child_wallet(
        parent_id, "keeper", Decimal("200"), Decimal("200")
    )
    assert await _stored_balance(parent_id) == before - Decimal("200")
    assert await _stored_balance(child.wallet_id) == Decimal("200")


# --- Reclaim ----------------------------------------------------------------


async def test_reclaim_restores_parent_and_closes_child(money, agent_pair):
    parent_id = agent_pair[0].wallet_id
    before = await _stored_balance(parent_id)
    child = await money.create_child_wallet(
        parent_id, "temp", Decimal("300"), Decimal("300")
    )
    result = await money.reclaim_child_wallet(child.wallet_id)
    assert result["credits_reclaimed"] == Decimal("300")
    assert result["parent_balance_after"] == before
    assert await _stored_balance(parent_id) == before
    assert await _stored_status(child.wallet_id) == "closed"


async def test_double_reclaim_rejected(money, agent_pair):
    child = await money.create_child_wallet(
        agent_pair[0].wallet_id, "once", Decimal("50"), Decimal("50")
    )
    await money.reclaim_child_wallet(child.wallet_id)
    with pytest.raises(ValueError, match="already closed"):
        await money.reclaim_child_wallet(child.wallet_id)


async def test_reclaim_non_child_rejected(money, agent_pair):
    with pytest.raises(ValueError, match="child"):
        await money.reclaim_child_wallet(agent_pair[0].wallet_id)


async def test_reclaim_missing_wallet_raises(money):
    with pytest.raises(WalletNotFoundError):
        await money.reclaim_child_wallet("chd-missing")


# --- Transfers --------------------------------------------------------------


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-5")])
async def test_transfer_nonpositive_amount_rejected(money, agent_pair, bad):
    with pytest.raises(ValueError, match="positive"):
        await money.transfer(agent_pair[0].wallet_id, agent_pair[1].wallet_id, bad)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
async def test_transfer_nonfinite_amount_rejected(money, agent_pair, bad):
    with pytest.raises(ValueError, match="positive"):
        await money.transfer(agent_pair[0].wallet_id, agent_pair[1].wallet_id, bad)


async def test_transfer_same_wallet_rejected(money, agent_pair):
    with pytest.raises(ValueError, match="same wallet"):
        await money.transfer(
            agent_pair[0].wallet_id, agent_pair[0].wallet_id, Decimal("1")
        )


async def test_transfer_missing_wallets_raise(money, agent_pair):
    with pytest.raises(WalletNotFoundError):
        await money.transfer("agt-missing", agent_pair[1].wallet_id, Decimal("1"))
    with pytest.raises(WalletNotFoundError):
        await money.transfer(agent_pair[0].wallet_id, "agt-missing", Decimal("1"))


async def test_transfer_insufficient_reports_shortfall(money, agent_pair):
    with pytest.raises(InsufficientFundsError) as exc_info:
        await money.transfer(
            agent_pair[1].wallet_id, agent_pair[0].wallet_id, Decimal("500")
        )
    assert exc_info.value.shortfall == Decimal("400")


async def test_transfer_conserves_funds_and_links_ledger(money, agent_pair):
    src, dst = agent_pair[0].wallet_id, agent_pair[1].wallet_id
    src_before = await _stored_balance(src)
    dst_before = await _stored_balance(dst)
    result = await money.transfer(
        src, dst, Decimal("40"), "qa handoff", correlation_id="qa-corr-1"
    )
    assert result["status"] == "completed"
    assert result["from_balance_after"] == src_before - Decimal("40")
    assert result["to_balance_after"] == dst_before + Decimal("40")
    assert await _stored_balance(src) + await _stored_balance(dst) == (
        src_before + dst_before
    )
    src_entries = await money.get_ledger(src)
    dst_entries = await money.get_ledger(dst)
    assert Decimal(src_entries[0].amount_exact) == Decimal("-40")
    assert Decimal(dst_entries[0].amount_exact) == Decimal("40")
    assert Decimal(src_entries[0].balance_after_exact) == src_before - Decimal("40")
    assert Decimal(dst_entries[0].balance_after_exact) == dst_before + Decimal("40")
    async with get_session_factory()() as session:
        from sqlalchemy import select

        rows = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.correlation_id == "qa-corr-1",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.wallet_id for r in rows} == {src, dst}


@pytest.mark.parametrize("status", ["frozen", "closed", "suspended"])
async def test_transfer_into_unspendable_destination_rejected(
    money, agent_pair, status
):
    """Credits must not be parked where no path can spend or reclaim them."""
    src, dst = agent_pair[0].wallet_id, agent_pair[1].wallet_id
    await _set_status(dst, status)
    src_before = await _stored_balance(src)
    dst_before = await _stored_balance(dst)
    with pytest.raises(ValueError, match="Destination wallet"):
        await money.transfer(src, dst, Decimal("10"))
    assert await _stored_balance(src) == src_before
    assert await _stored_balance(dst) == dst_before


async def test_transfer_from_expired_child_rejected(money, agent_pair):
    child = await money.create_child_wallet(
        agent_pair[0].wallet_id,
        "short-lived",
        Decimal("50"),
        Decimal("50"),
        ttl_seconds=3600,
    )
    async with get_session_factory()() as session:
        async with session.begin():
            row = await session.get(WalletModel, child.wallet_id)
            assert row is not None
            row.created_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) - timedelta(hours=2)
    assert await money.wallet_is_expired(child.wallet_id) is True
    with pytest.raises(Exception, match="expired"):
        await money.transfer(child.wallet_id, agent_pair[1].wallet_id, Decimal("5"))


# --- Hierarchy / authorization helper ----------------------------------------


async def test_descendant_check_self_child_and_unrelated(money, sponsor, agent_pair):
    child = await money.create_child_wallet(
        agent_pair[0].wallet_id, "depth", Decimal("10"), Decimal("10")
    )
    assert (
        await money.is_wallet_or_descendant(
            agent_pair[0].wallet_id, agent_pair[0].wallet_id
        )
        is True
    )
    assert (
        await money.is_wallet_or_descendant(child.wallet_id, sponsor.wallet_id) is True
    )
    assert (
        await money.is_wallet_or_descendant(
            agent_pair[1].wallet_id, agent_pair[0].wallet_id
        )
        is False
    )
    assert (
        await money.is_wallet_or_descendant("agt-missing", sponsor.wallet_id) is False
    )


async def test_descendant_check_cycle_terminates(money, sponsor, agent_pair):
    child = await money.create_child_wallet(
        agent_pair[0].wallet_id, "loopy", Decimal("10"), Decimal("10")
    )
    async with get_session_factory()() as session:
        async with session.begin():
            parent = await session.get(WalletModel, agent_pair[0].wallet_id)
            assert parent is not None
            parent.parent_wallet_id = child.wallet_id
    assert (
        await money.is_wallet_or_descendant(child.wallet_id, sponsor.wallet_id) is False
    )


# --- Reads ------------------------------------------------------------------


# --- Charges, refunds, dry-run (billing_engine, test-only) -------------------


@pytest.mark.parametrize(
    "units", [Decimal("0"), Decimal("-2"), Decimal("NaN"), Decimal("Infinity")]
)
async def test_charge_rejects_bad_units(money, agent_pair, units):
    """Non-positive or non-finite units must raise, never mint or write."""
    wallet_id = agent_pair[0].wallet_id
    before = await _stored_balance(wallet_id)
    with pytest.raises(ValueError, match="units must be"):
        await money.charge(wallet_id, PLATFORM_FEE, units=units)
    assert await _stored_balance(wallet_id) == before


async def test_charge_beyond_balance_returns_shortfall_without_moving_funds(
    money, agent_pair
):
    wallet_id = agent_pair[1].wallet_id
    before = await _stored_balance(wallet_id)
    result = await money.charge(wallet_id, PLATFORM_FEE, units=Decimal("1000000"))
    assert result.error == "insufficient_funds"
    assert Decimal(result.shortfall_exact) > Decimal("0")
    assert await _stored_balance(wallet_id) == before


async def test_charge_debits_exact_price_and_writes_ledger(money, agent_pair):
    wallet_id = agent_pair[0].wallet_id
    units = Decimal("3")
    expected = _charge_amount(money, units)
    before = await _stored_balance(wallet_id)
    result = await money.charge(wallet_id, PLATFORM_FEE, units=units)
    assert Decimal(result.amount_exact) == -expected
    assert Decimal(result.balance_after_exact) == before - expected
    assert await _stored_balance(wallet_id) == before - expected


async def test_dry_run_moves_nothing(money, agent_pair):
    wallet_id = agent_pair[0].wallet_id
    before = await _stored_balance(wallet_id)
    units = Decimal("2")
    expected = _charge_amount(money, units)
    ledger_before = await money.get_ledger(wallet_id)
    result = await money.charge(wallet_id, PLATFORM_FEE, units=units, dry_run=True)
    assert result.would_succeed is True
    assert result.credits_would_charge == expected
    assert result.simulated_balance_after == before - expected
    assert await _stored_balance(wallet_id) == before
    assert await money.get_ledger(wallet_id) == ledger_before


async def test_dry_run_reports_insufficient_without_side_effects(money, agent_pair):
    wallet_id = agent_pair[1].wallet_id
    result = await money.charge(
        wallet_id, PLATFORM_FEE, units=Decimal("1000000"), dry_run=True
    )
    assert result.would_succeed is False
    assert result.reason == "insufficient_simulated_funds"


async def test_refund_restores_balance_and_is_idempotent(money, agent_pair):
    wallet_id = agent_pair[0].wallet_id
    units = Decimal("4")
    expected = _charge_amount(money, units)
    before = await _stored_balance(wallet_id)
    charge = await money.charge(wallet_id, PLATFORM_FEE, units=units)
    first = await money.refund_charge(
        wallet_id=wallet_id, charge_entry_id=charge.entry_id
    )
    assert Decimal(first.amount_exact) == expected
    assert await _stored_balance(wallet_id) == before
    second = await money.refund_charge(
        wallet_id=wallet_id, charge_entry_id=charge.entry_id
    )
    assert second.entry_id == first.entry_id
    assert await _stored_balance(wallet_id) == before


async def test_top_up_direct_minting_disabled(money, agent_pair):
    with pytest.raises(DirectTopUpDisabledError):
        await money.top_up(agent_pair[0].wallet_id, Decimal("10"))


async def _make_operation_record(wallet_id: str, operation_key: str) -> None:
    async with get_session_factory()() as session:
        async with session.begin():
            session.add(
                IdempotencyRecordModel(
                    record_id=operation_key,
                    wallet_id=wallet_id,
                    endpoint="/v1/billing/charge",
                    idempotency_key=operation_key,
                    request_hash="c" * 64,
                )
            )


async def test_governed_charge_replay_returns_same_debit(money, agent_pair):
    """Same operation key twice: one debit, same entry, no double charge."""
    wallet_id = agent_pair[0].wallet_id
    operation_key = "qa-op-replay"
    await _make_operation_record(wallet_id, operation_key)
    before = await _stored_balance(wallet_id)
    first = await money.charge(
        wallet_id, PLATFORM_FEE, units=Decimal("2"), operation_key=operation_key
    )
    second = await money.charge(
        wallet_id, PLATFORM_FEE, units=Decimal("2"), operation_key=operation_key
    )
    assert second.entry_id == first.entry_id
    expected = _charge_amount(money, Decimal("2"))
    assert await _stored_balance(wallet_id) == before - expected
    async with get_session_factory()() as session:
        from sqlalchemy import select

        rows = (
            (
                await session.execute(
                    select(LedgerEntryModel).where(
                        LedgerEntryModel.wallet_id == wallet_id,
                        LedgerEntryModel.operation_key == operation_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_governed_charge_key_reuse_with_different_amount_conflicts(
    money, agent_pair
):
    """One operation key must never describe two different debits."""
    wallet_id = agent_pair[0].wallet_id
    operation_key = "qa-op-conflict"
    await _make_operation_record(wallet_id, operation_key)
    await money.charge(
        wallet_id, PLATFORM_FEE, units=Decimal("1"), operation_key=operation_key
    )
    with pytest.raises(
        LedgerOperationConflictError, match="ledger_operation_key_reused"
    ):
        await money.charge(
            wallet_id, PLATFORM_FEE, units=Decimal("5"), operation_key=operation_key
        )


async def test_governed_charge_without_record_rejected(money, agent_pair):
    with pytest.raises(ValueError, match="ledger_operation_record_not_found"):
        await money.charge(
            agent_pair[0].wallet_id,
            PLATFORM_FEE,
            units=Decimal("1"),
            operation_key="qa-op-no-record",
        )


@pytest.mark.xfail(
    strict=True,
    reason="billing_engine.get_ledger does not validate limit: "
    "limit=-1 reaches SQLite as LIMIT -1 (unlimited) instead of raising; "
    "router validates ge=1 but the service layer does not. "
    "Owned by in-flight billing work, noted for the reviewer.",
)
async def test_ledger_negative_limit_rejected(money, agent_pair):
    await money.charge(agent_pair[0].wallet_id, PLATFORM_FEE, units=Decimal("1"))
    with pytest.raises(ValueError, match="limit"):
        await money.get_ledger(agent_pair[0].wallet_id, limit=-1)
