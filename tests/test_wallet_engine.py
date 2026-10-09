"""Focused coverage for app/services/wallet_engine.py.

Exercises the wallet lifecycle through the real WalletEngine (reached via
the AgentMoney facade, which delegates wallet work to it): sponsor and agent
creation, agent-to-agent transfers, child delegation and reclaim, wallet
reads, TTL validation, and the main edge and error cases.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.agent_money import (
    InsufficientFundsError,
    WalletNotFoundError,
    get_agent_money,
)
from app.services.wallet_engine import (
    MAX_CHILD_WALLET_TTL_SECONDS,
    WalletExpiredError,
    child_wallet_expires_at,
)


async def _sponsor_with_agent(
    clean_database, *, initial=Decimal("100"), budget=Decimal("40")
):
    money = get_agent_money()
    sponsor = await money.create_sponsor_wallet("Sponsor", "s@example.test", initial)
    agent = await money.create_agent_wallet(sponsor.wallet_id, "agent-1", budget)
    return money, sponsor, agent


async def test_sponsor_and_agent_creation_moves_funds(clean_database):
    money = get_agent_money()
    sponsor = await money.create_sponsor_wallet(
        "Sponsor", "s@example.test", Decimal("100")
    )
    assert sponsor.balance == Decimal("100")

    agent = await money.create_agent_wallet(sponsor.wallet_id, "agent-1", Decimal("40"))
    assert agent.balance == Decimal("40")

    sponsor_after = await money.get_wallet(sponsor.wallet_id)
    assert sponsor_after is not None
    assert sponsor_after.balance == Decimal("60")


async def test_agent_wallet_rejects_negative_budget(clean_database):
    money, sponsor, _ = await _sponsor_with_agent(clean_database)
    with pytest.raises(ValueError, match="cannot be negative"):
        await money.create_agent_wallet(sponsor.wallet_id, "agent-neg", Decimal("-5"))


async def test_agent_wallet_from_missing_sponsor_raises_not_found(clean_database):
    money = get_agent_money()
    with pytest.raises(WalletNotFoundError):
        await money.create_agent_wallet("spn-missing", "agent-1", Decimal("10"))


async def test_agent_wallet_with_insufficient_sponsor_funds(clean_database):
    money, sponsor, _ = await _sponsor_with_agent(clean_database)
    with pytest.raises(InsufficientFundsError):
        await money.create_agent_wallet(sponsor.wallet_id, "agent-2", Decimal("1000"))


async def test_transfer_moves_funds_between_agents(clean_database):
    money, _, agent = await _sponsor_with_agent(clean_database)
    sponsor = await money.create_sponsor_wallet("S2", "s2@example.test", Decimal("100"))
    receiver = await money.create_agent_wallet(
        sponsor.wallet_id, "agent-2", Decimal("10")
    )

    receipt = await money.transfer(agent.wallet_id, receiver.wallet_id, Decimal("15"))
    assert receipt["status"] == "completed"
    assert receipt["from_balance_after"] == Decimal("25")
    assert receipt["to_balance_after"] == Decimal("25")


async def test_transfer_rejects_bad_amounts_and_unknown_wallets(clean_database):
    money, sponsor, agent = await _sponsor_with_agent(clean_database)
    with pytest.raises(ValueError, match="positive"):
        await money.transfer(agent.wallet_id, "agt-other", Decimal("0"))
    with pytest.raises(ValueError, match="same wallet"):
        await money.transfer(agent.wallet_id, agent.wallet_id, Decimal("1"))
    with pytest.raises(WalletNotFoundError):
        await money.transfer(agent.wallet_id, "agt-missing", Decimal("1"))
    receiver = await money.create_agent_wallet(
        sponsor.wallet_id, "agent-2", Decimal("10")
    )
    with pytest.raises(InsufficientFundsError):
        await money.transfer(agent.wallet_id, receiver.wallet_id, Decimal("1000"))


async def test_child_delegation_and_reclaim_round_trip(clean_database):
    money, _, agent = await _sponsor_with_agent(clean_database)
    child = await money.create_child_wallet(
        agent.wallet_id,
        "child-1",
        Decimal("20"),
        Decimal("20"),
        task_description="subtask",
    )
    assert child.balance == Decimal("20")

    budget = await money.get_swarm_budget(agent.wallet_id)
    assert budget["active_children"] == 1
    assert budget["total_delegated"] == Decimal("20")

    receipt = await money.reclaim_child_wallet(child.wallet_id)
    assert receipt["credits_reclaimed"] == Decimal("20")
    assert receipt["parent_balance_after"] == Decimal("40")

    with pytest.raises(ValueError, match="already closed"):
        await money.reclaim_child_wallet(child.wallet_id)


async def test_child_wallet_rejects_bad_ttl_and_negative_budget(clean_database):
    money, _, agent = await _sponsor_with_agent(clean_database)
    with pytest.raises(ValueError, match="ttl_seconds"):
        await money.create_child_wallet(
            agent.wallet_id,
            "child-bad-ttl",
            Decimal("5"),
            Decimal("5"),
            ttl_seconds=0,
        )
    with pytest.raises(ValueError, match="ttl_seconds"):
        await money.create_child_wallet(
            agent.wallet_id,
            "child-big-ttl",
            Decimal("5"),
            Decimal("5"),
            ttl_seconds=MAX_CHILD_WALLET_TTL_SECONDS + 1,
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        await money.create_child_wallet(
            agent.wallet_id,
            "child-neg",
            Decimal("-5"),
            Decimal("5"),
        )


async def test_wallet_reads_list_and_daily_spend(clean_database):
    money, sponsor, agent = await _sponsor_with_agent(clean_database)
    assert (await money.get_wallet("spn-missing")) is None
    wallets = await money.list_wallets()
    ids = {w.wallet_id for w in wallets}
    assert {sponsor.wallet_id, agent.wallet_id} <= ids
    agents = await money.list_wallets(wallet_type="agent")
    assert all(w.wallet_type == "agent" for w in agents)
    assert await money.get_daily_spend(agent.wallet_id) == Decimal("0")
    assert await money.get_daily_spend("agt-missing") == Decimal("0")
    assert await money.wallet_is_expired(agent.wallet_id) is False
    assert await money.wallet_is_expired("agt-missing") is False


async def test_reclaim_rejects_non_child_wallets(clean_database):
    money, _, agent = await _sponsor_with_agent(clean_database)
    with pytest.raises(ValueError, match="Can only reclaim from child wallets"):
        await money.reclaim_child_wallet(agent.wallet_id)
    with pytest.raises(WalletNotFoundError):
        await money.reclaim_child_wallet("chd-missing")


def test_child_wallet_expiry_helper_and_expired_error():
    from datetime import timedelta

    from app.db.models import WalletModel

    agent = WalletModel(wallet_id="agt-x", wallet_type="agent", ttl_seconds=60)
    assert child_wallet_expires_at(agent) is None

    child = WalletModel(
        wallet_id="chd-x",
        wallet_type="child",
        ttl_seconds=3600,
    )
    assert child_wallet_expires_at(child) == child.created_at + timedelta(seconds=3600)

    err = WalletExpiredError("chd-x", child.created_at)
    assert "chd-x" in str(err)
    assert err.wallet_id == "chd-x"
