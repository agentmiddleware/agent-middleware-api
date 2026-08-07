"""Wallet lifecycle and hierarchy engine used by AgentMoney.

This module owns wallet creation, delegation, reclaim, transfer, locking, and
wallet reads. The public compatibility surface remains AgentMoney.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from ..core.config import Settings
from ..db.converters import wallet_model_to_response
from ..db.models import LedgerEntryModel, WalletModel
from ..schemas.billing import (
    KYCStatus,
    LedgerAction,
    WalletResponse,
    WalletStatus,
    WalletType,
)

logger = logging.getLogger(__name__)

_NON_SPENDABLE_WALLET_STATUSES = frozenset(
    {
        WalletStatus.FROZEN.value,
        WalletStatus.SUSPENDED.value,
        WalletStatus.CLOSED.value,
    }
)

SessionFactoryProvider = Callable[[], async_sessionmaker[AsyncSession]]
WalletNotFoundFactory = Callable[[str], Exception]
InsufficientFundsFactory = Callable[[str, Decimal, Decimal], Exception]
MetadataSerializer = Callable[[dict | None], str | None]


class WalletEngine:
    """Internal wallet lifecycle implementation behind AgentMoney."""

    def __init__(
        self,
        *,
        session_factory: SessionFactoryProvider,
        settings: Settings,
        wallet_not_found_error: WalletNotFoundFactory,
        insufficient_funds_error: InsufficientFundsFactory,
        metadata_to_json: MetadataSerializer,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._wallet_not_found_error = wallet_not_found_error
        self._insufficient_funds_error = insufficient_funds_error
        self._metadata_to_json = metadata_to_json

    async def _lock_wallets_in_order(
        self, session: AsyncSession, wallet_ids: list[str]
    ) -> dict[str, WalletModel]:
        """Lock each wallet row ``FOR UPDATE`` in a globally consistent order
        (sorted by wallet_id) via one statement per row.

        Every multi-wallet money operation (transfer, child reclaim) must
        acquire its locks through this helper so two operations touching the
        same pair can never deadlock by taking the locks in opposite orders.
        A single ``WHERE wallet_id IN (...)`` does NOT guarantee lock order --
        Postgres locks rows in scan order, not in the IN-list order -- which is
        why the locks are taken one at a time here.
        """
        locked: dict[str, WalletModel] = {}
        for wid in sorted(set(wallet_ids)):
            row = (
                await session.execute(
                    select(WalletModel)
                    .where(cast(ColumnElement[bool], WalletModel.wallet_id == wid))
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is not None:
                locked[wid] = row
        return locked

    # --- Wallet Management ---

    async def create_sponsor_wallet(
        self,
        sponsor_name: str,
        email: str,
        initial_credits: Decimal = Decimal("0"),
        currency: str = "USD",
        metadata: dict | None = None,
        require_kyc: bool | None = None,
    ) -> WalletResponse:
        """Create a human sponsor (liability sink) root wallet."""
        kyc_required = (
            require_kyc
            if require_kyc is not None
            else self._settings.KYC_REQUIRED_FOR_TOPUP
        )

        async with self._session_factory()() as session:
            async with session.begin():
                wallet_id = f"spn-{uuid.uuid4().hex[:12]}"

                wallet = WalletModel(
                    wallet_id=wallet_id,
                    wallet_type=WalletType.SPONSOR.value,
                    owner_name=sponsor_name,
                    email=email,
                    balance=initial_credits,
                    lifetime_credits=initial_credits,
                    currency=currency,
                    metadata_json=self._metadata_to_json(metadata),
                    kyc_status=(
                        KYCStatus.PENDING.value
                        if kyc_required
                        else KYCStatus.NOT_REQUIRED.value
                    ),
                    status="pending_kyc" if kyc_required else "active",
                )
                session.add(wallet)
                # Flush before ledger insert: with autoflush=False the UOW can
                # INSERT ledger_entries before wallets, violating
                # ledger_entries_wallet_id_fkey on Postgres.
                await session.flush()

                if initial_credits > Decimal("0"):
                    entry = LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=wallet_id,
                        action=LedgerAction.CREDIT.value,
                        amount=initial_credits,
                        balance_after=initial_credits,
                        description="Initial sponsor deposit",
                    )
                    session.add(entry)

            await session.commit()
            logger.info(f"Created sponsor wallet {wallet_id} for {sponsor_name}")
            return wallet_model_to_response(wallet)

    async def create_agent_wallet(
        self,
        sponsor_wallet_id: str,
        agent_id: str,
        budget_credits: Decimal,
        daily_limit: Decimal | None = None,
        auto_refill: bool = False,
        auto_refill_threshold: Decimal = Decimal("100.0"),
        auto_refill_amount: Decimal = Decimal("1000.0"),
    ) -> WalletResponse:
        """Provision a pre-paid agent wallet from a sponsor's balance."""
        async with self._session_factory()() as session:
            async with session.begin():
                # Lock sponsor wallet for update
                result = await session.execute(
                    select(WalletModel)
                    .where(
                        cast(
                            ColumnElement[bool],
                            WalletModel.wallet_id == sponsor_wallet_id,
                        )
                    )
                    .with_for_update()
                )
                sponsor = result.scalar_one_or_none()

                if not sponsor:
                    raise self._wallet_not_found_error(sponsor_wallet_id)
                if sponsor.wallet_type != WalletType.SPONSOR.value:
                    raise ValueError(
                        "Can only provision agent wallets from sponsor wallets"
                    )
                if sponsor.balance < budget_credits:
                    raise self._insufficient_funds_error(
                        sponsor_wallet_id,
                        sponsor.balance,
                        budget_credits,
                    )

                # Deduct from sponsor
                sponsor.balance -= budget_credits
                sponsor.lifetime_debits += budget_credits

                # Create agent wallet
                agent_wallet_id = f"agt-{uuid.uuid4().hex[:12]}"
                agent_wallet = WalletModel(
                    wallet_id=agent_wallet_id,
                    wallet_type=WalletType.AGENT.value,
                    owner_name=f"Agent: {agent_id}",
                    balance=budget_credits,
                    lifetime_credits=budget_credits,
                    parent_wallet_id=sponsor_wallet_id,
                    agent_id=agent_id,
                    daily_limit=daily_limit,
                    auto_refill=auto_refill,
                    auto_refill_threshold=auto_refill_threshold,
                    auto_refill_amount=auto_refill_amount,
                )
                session.add(agent_wallet)
                # Persist new wallet before ledger rows that FK to it.
                await session.flush()

                # Ledger entries
                session.add(
                    LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=sponsor_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=-budget_credits,
                        balance_after=sponsor.balance,
                        description=(
                            f"Provision agent wallet {agent_wallet_id} for {agent_id}"
                        ),
                    )
                )
                session.add(
                    LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=agent_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=budget_credits,
                        balance_after=budget_credits,
                        description=f"Provisioned from sponsor {sponsor_wallet_id}",
                    )
                )

            await session.commit()
            logger.info(
                f"Created agent wallet {agent_wallet_id} with {budget_credits} credits"
            )
            return wallet_model_to_response(agent_wallet)

    # --- Child Wallet Management (Swarm Delegation) ---

    async def create_child_wallet(
        self,
        parent_wallet_id: str,
        child_agent_id: str,
        budget_credits: Decimal,
        max_spend: Decimal,
        task_description: str = "",
        ttl_seconds: int | None = None,
        auto_reclaim: bool = True,
    ) -> WalletResponse:
        """Spawn a child sub-agent wallet from a parent agent's balance."""
        async with self._session_factory()() as session:
            async with session.begin():
                # Lock parent wallet
                result = await session.execute(
                    select(WalletModel)
                    .where(
                        cast(
                            ColumnElement[bool],
                            WalletModel.wallet_id == parent_wallet_id,
                        )
                    )
                    .with_for_update()
                )
                parent = result.scalar_one_or_none()

                if not parent:
                    raise self._wallet_not_found_error(parent_wallet_id)
                if parent.wallet_type not in (
                    WalletType.AGENT.value,
                    WalletType.CHILD.value,
                ):
                    raise ValueError(
                        "Only agent or child wallets can spawn child wallets"
                    )
                if parent.status in _NON_SPENDABLE_WALLET_STATUSES:
                    raise ValueError(
                        f"Parent wallet is {parent.status} and cannot spawn child wallets"
                    )
                if (
                    parent.wallet_type == WalletType.CHILD.value
                    and parent.max_spend
                    and parent.lifetime_debits + budget_credits > parent.max_spend
                ):
                    raise ValueError("Child wallet lifetime spend cap exceeded")
                if parent.balance < budget_credits:
                    raise self._insufficient_funds_error(
                        parent_wallet_id,
                        parent.balance,
                        budget_credits,
                    )

                # Deduct from parent
                parent.balance -= budget_credits
                parent.lifetime_debits += budget_credits

                # Create child wallet
                child_wallet_id = f"chd-{uuid.uuid4().hex[:12]}"
                child = WalletModel(
                    wallet_id=child_wallet_id,
                    wallet_type=WalletType.CHILD.value,
                    owner_name=f"Child: {child_agent_id}",
                    balance=budget_credits,
                    lifetime_credits=budget_credits,
                    parent_wallet_id=parent_wallet_id,
                    child_agent_id=child_agent_id,
                    max_spend=max_spend,
                    task_description=task_description,
                    ttl_seconds=ttl_seconds,
                )
                session.add(child)
                # Persist new wallet before ledger rows that FK to it.
                await session.flush()

                # Ledger entries
                session.add(
                    LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=parent_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=-budget_credits,
                        balance_after=parent.balance,
                        description=(
                            f"Delegate to child wallet {child_wallet_id} "
                            f"({child_agent_id})"
                        ),
                    )
                )
                session.add(
                    LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=child_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=budget_credits,
                        balance_after=budget_credits,
                        description=f"Provisioned from parent {parent_wallet_id}",
                    )
                )

            await session.commit()
            logger.info(f"Spawned child wallet {child_wallet_id} for {child_agent_id}")
            return wallet_model_to_response(child)

    async def reclaim_child_wallet(self, child_wallet_id: str) -> dict:
        """Reclaim unspent credits from a child wallet back to its parent."""
        async with self._session_factory()() as session:
            async with session.begin():
                # Discover the (immutable) parent id with an unlocked read, so
                # both rows can then be locked in the same globally consistent
                # sorted order that transfer() uses -- otherwise reclaim would
                # lock child-then-parent while a concurrent transfer locks the
                # sorted order, and the two could deadlock.
                child_peek = (
                    await session.execute(
                        select(WalletModel).where(
                            cast(
                                ColumnElement[bool],
                                WalletModel.wallet_id == child_wallet_id,
                            )
                        )
                    )
                ).scalar_one_or_none()
                if not child_peek:
                    raise self._wallet_not_found_error(child_wallet_id)
                if not child_peek.parent_wallet_id:
                    raise ValueError("Child wallet has no parent")
                parent_wallet_id = child_peek.parent_wallet_id

                locked = await self._lock_wallets_in_order(
                    session, [child_wallet_id, parent_wallet_id]
                )
                child = locked.get(child_wallet_id)
                parent = locked.get(parent_wallet_id)

                if not child:
                    raise self._wallet_not_found_error(child_wallet_id)
                if child.wallet_type != WalletType.CHILD.value:
                    raise ValueError("Can only reclaim from child wallets")
                if child.status == WalletStatus.CLOSED.value:
                    raise ValueError("Wallet already closed")
                if not parent:
                    raise self._wallet_not_found_error(parent_wallet_id)

                reclaim_amount = child.balance

                if reclaim_amount > Decimal("0"):
                    child.balance = Decimal("0")
                    parent.balance += reclaim_amount
                    parent.lifetime_credits += reclaim_amount

                    # Ledger entries
                    session.add(
                        LedgerEntryModel(
                            entry_id=str(uuid.uuid4()),
                            wallet_id=child_wallet_id,
                            action=LedgerAction.TRANSFER.value,
                            amount=-reclaim_amount,
                            balance_after=Decimal("0"),
                            description=f"Reclaimed to parent {parent.wallet_id}",
                        )
                    )
                    session.add(
                        LedgerEntryModel(
                            entry_id=str(uuid.uuid4()),
                            wallet_id=parent.wallet_id,
                            action=LedgerAction.TRANSFER.value,
                            amount=reclaim_amount,
                            balance_after=parent.balance,
                            description=f"Reclaimed from child {child_wallet_id}",
                        )
                    )

                child.status = WalletStatus.CLOSED.value

            await session.commit()

            return {
                "child_wallet_id": child_wallet_id,
                "parent_wallet_id": parent.wallet_id,
                "credits_reclaimed": reclaim_amount,
                "parent_balance_after": parent.balance,
                "child_status": WalletStatus(child.status),
            }

    # --- Agent-to-Agent Transfers ---

    async def transfer(
        self,
        from_wallet_id: str,
        to_wallet_id: str,
        amount: Decimal,
        description: str = "",
        correlation_id: str | None = None,
    ) -> dict:
        """
        Transfer credits between two wallets (agent-to-agent handoff).

        This enables agents to pay each other for completed tasks.
        Both wallets are locked during the transaction for ACID compliance.

        Args:
            from_wallet_id: Source wallet (must have sufficient balance)
            to_wallet_id: Destination wallet
            amount: Credits to transfer (must be > 0)
            description: Optional description of the transfer
            correlation_id: Optional ID to link related transfers

        Returns:
            Transfer receipt with both wallet balances

        Raises:
            WalletNotFoundError: If either wallet doesn't exist
            InsufficientFundsError: If source has insufficient balance
            ValueError: If amount <= 0 or same wallet IDs
        """
        if amount <= Decimal("0"):
            raise ValueError("Transfer amount must be positive")

        if from_wallet_id == to_wallet_id:
            raise ValueError("Cannot transfer to the same wallet")

        async with self._session_factory()() as session:
            async with session.begin():
                # Lock both wallets in a globally consistent (sorted) order via
                # one FOR UPDATE per row, so a concurrent transfer/reclaim on
                # the same pair cannot deadlock.
                wallets = await self._lock_wallets_in_order(
                    session, [from_wallet_id, to_wallet_id]
                )

                source = wallets.get(from_wallet_id)
                dest = wallets.get(to_wallet_id)

                if not source:
                    raise self._wallet_not_found_error(from_wallet_id)
                if not dest:
                    raise self._wallet_not_found_error(to_wallet_id)

                if source.status in _NON_SPENDABLE_WALLET_STATUSES:
                    raise ValueError(
                        f"Source wallet is {source.status} and cannot transfer credits"
                    )
                if (
                    source.wallet_type == WalletType.CHILD.value
                    and source.max_spend
                    and source.lifetime_debits + amount > source.max_spend
                ):
                    raise ValueError("Child wallet lifetime spend cap exceeded")

                if source.balance < amount:
                    raise self._insufficient_funds_error(
                        from_wallet_id, source.balance, amount
                    )

                # Execute transfer
                source.balance -= amount
                source.lifetime_debits += amount
                dest.balance += amount
                dest.lifetime_credits += amount

                # Create ledger entries on both sides
                session.add(
                    LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=from_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=-amount,
                        balance_after=source.balance,
                        description=description or f"Transfer to {to_wallet_id}",
                        correlation_id=correlation_id,
                    )
                )
                session.add(
                    LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=to_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=amount,
                        balance_after=dest.balance,
                        description=description or f"Transfer from {from_wallet_id}",
                        correlation_id=correlation_id,
                    )
                )

            await session.commit()

            logger.info(
                f"Transfer {amount} credits from {from_wallet_id} to {to_wallet_id}"
            )

            return {
                "transfer_id": correlation_id or str(uuid.uuid4()),
                "from_wallet_id": from_wallet_id,
                "to_wallet_id": to_wallet_id,
                "amount": amount,
                "from_balance_after": source.balance,
                "to_balance_after": dest.balance,
                "status": "completed",
            }

    async def get_swarm_budget(self, parent_wallet_id: str) -> dict:
        """Get hierarchical budget summary for an agent's child swarm."""
        async with self._session_factory()() as session:
            # Get parent
            parent_result = await session.execute(
                select(WalletModel).where(
                    cast(ColumnElement[bool], WalletModel.wallet_id == parent_wallet_id)
                )
            )
            parent = parent_result.scalar_one_or_none()

            if not parent:
                raise self._wallet_not_found_error(parent_wallet_id)

            # Get children
            children_result = await session.execute(
                select(WalletModel).where(
                    cast(
                        ColumnElement[bool],
                        WalletModel.parent_wallet_id == parent_wallet_id,
                    )
                )
            )
            children = list(children_result.scalars().all())

            total_delegated = sum(w.lifetime_credits for w in children)
            total_reclaimed = sum(
                w.lifetime_credits - w.balance - w.lifetime_debits
                for w in children
                if w.status == WalletStatus.CLOSED.value
            )
            active = [w for w in children if w.status == WalletStatus.ACTIVE.value]
            completed = [w for w in children if w.status == WalletStatus.CLOSED.value]
            frozen = [w for w in children if w.status == WalletStatus.FROZEN.value]

            return {
                "parent_wallet_id": parent_wallet_id,
                "parent_balance": parent.balance,
                "total_delegated": total_delegated,
                "total_reclaimed": total_reclaimed,
                "active_children": len(active),
                "completed_children": len(completed),
                "frozen_children": len(frozen),
                "children": [wallet_model_to_response(w) for w in children],
            }

    # --- Wallet Queries ---

    async def get_wallet(self, wallet_id: str) -> WalletResponse | None:
        """Get a wallet by ID."""
        async with self._session_factory()() as session:
            result = await session.execute(
                select(WalletModel).where(
                    cast(ColumnElement[bool], WalletModel.wallet_id == wallet_id)
                )
            )
            wallet = result.scalar_one_or_none()
            if wallet:
                return wallet_model_to_response(wallet)
            return None

    async def get_daily_spend(self, wallet_id: str) -> Decimal:
        """Return the wallet's spend in the current daily window.

        Read-only and reset-aware: if the daily window has rolled over since the
        last reset (mirroring the velocity monitor's rule), the effective spend
        is 0 even though it hasn't been persisted yet. Returns 0 for unknown
        wallets so callers can treat it as "no spend recorded".
        """
        async with self._session_factory()() as session:
            result = await session.execute(
                select(WalletModel).where(
                    cast(ColumnElement[bool], WalletModel.wallet_id == wallet_id)
                )
            )
            wallet = result.scalar_one_or_none()
            if not wallet:
                return Decimal("0")
            reset_at = wallet.daily_reset_at
            if reset_at is None:
                return Decimal("0")
            if reset_at.tzinfo is None:
                reset_at = reset_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - reset_at >= timedelta(days=1):
                return Decimal("0")
            return wallet.daily_spent

    async def list_wallets(
        self,
        wallet_type: str | None = None,
    ) -> list[WalletResponse]:
        """List wallets with optional filtering."""
        async with self._session_factory()() as session:
            query = select(WalletModel)
            if wallet_type:
                enum_val = WalletType(wallet_type).value if wallet_type else None
                if enum_val:
                    query = query.where(
                        cast(ColumnElement[bool], WalletModel.wallet_type == enum_val)
                    )
            result = await session.execute(query)
            wallets = list(result.scalars().all())
            return [wallet_model_to_response(w) for w in wallets]
