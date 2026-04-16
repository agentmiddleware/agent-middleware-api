"""
Agent Financial Gateways — Service Layer (v2)
==============================================
The economic engine for the B2A economy.

Architecture:
┌─────────────────────────────────────────────┐
│ Human Sponsor (Liability Sink)              │
│ ┌─────────────┐    ┌────────────────────┐   │
│ │ Fiat Rails  │───>│  Sponsor Wallet    │   │
│ │ (Stripe)    │    │  balance: $50,000  │   │
│ └─────────────┘    └────────┬───────────┘   │
│                             │ provision     │
│              ┌──────────────┼───────────┐   │
│              │              │           │   │
│         ┌────▼────┐   ┌────▼────┐  ┌───▼──┐│
│         │Agent W1 │   │Agent W2 │  │ ...  ││
│         │10K cred │   │5K cred  │  │      ││
│         └────┬────┘   └────┬────┘  └──────┘│
│              │ debit       │ debit          │
│         ┌────▼────────────▼─────┐          │
│         │  Per-Action Ledger    │          │
│         │  (micro-metering)     │          │
│         └───────────────────────┘          │
└─────────────────────────────────────────────┘

Production wiring:
- PostgreSQL for ACID-compliant ledger
- Redis for real-time balance caching
- Stripe SDK for fiat ingestion
- Kafka for async ledger events

IMPORTANT: This service uses SQLModel with ACID transactions.
All monetary fields are Decimal for precision.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.durable_state import get_durable_state
from ..core.config import get_settings
from ..db.database import get_session_factory
from ..db.models import WalletModel, LedgerEntryModel, BillingAlertModel, ServiceRegistryModel
from ..db.converters import (
    wallet_model_to_response,
    ledger_entry_model_to_schema,
    billing_alert_model_to_schema,
)
from ..services.velocity_monitor import get_velocity_monitor, WalletFrozenError
from ..services.shadow_ledger import get_shadow_ledger, SimulatedChargeResult
from ..schemas.billing import (
    WalletType,
    WalletStatus,
    LedgerAction,
    ServiceCategory,
    TopUpStatus,
    AlertType,
    AlertSeverity,
    KYCStatus,
    WalletResponse,
    LedgerEntry,
    TopUpResponse,
    InsufficientFundsResponse,
    ServicePricing,
    ArbitrageReport,
    BillingAlert,
    ServiceRegistration,
)

settings = get_settings()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing Table (now using Decimal)
# ---------------------------------------------------------------------------

# Credits per unit for each service. 1000 credits ≈ $1 USD.
DEFAULT_PRICING: dict[ServiceCategory, tuple[str, Decimal, str]] = {
    ServiceCategory.IOT_BRIDGE: ("request", Decimal("2.0"), "Per IoT message bridged"),
    ServiceCategory.TELEMETRY_PM: ("event", Decimal("1.0"), "Per telemetry event ingested"),
    ServiceCategory.MEDIA_ENGINE: ("frame", Decimal("0.5"), "Per video frame processed"),
    ServiceCategory.AGENT_COMMS: ("message", Decimal("1.5"), "Per agent message routed"),
    ServiceCategory.CONTENT_FACTORY: ("piece", Decimal("50.0"), "Per content piece generated"),
    ServiceCategory.RED_TEAM: ("scan", Decimal("100.0"), "Per security scan executed"),
    ServiceCategory.ORACLE: ("crawl", Decimal("25.0"), "Per API crawled and indexed"),
    ServiceCategory.PLATFORM_FEE: ("request", Decimal("0.1"), "Base platform fee per API call"),
    ServiceCategory.SWARM_DELEGATION: ("child", Decimal("5.0"), "Per child wallet spawned"),
    ServiceCategory.PROTOCOL_GEN: ("generation", Decimal("200.0"), "Per llm.txt + OpenAPI spec generated"),
    ServiceCategory.SANDBOX: ("session", Decimal("150.0"), "Per sandbox environment session"),
    ServiceCategory.RTAAS: ("scan", Decimal("100.0"), "Per external Red Team scan"),
}

# Internal compute costs (what it actually costs us to serve)
COMPUTE_COSTS: dict[ServiceCategory, Decimal] = {
    ServiceCategory.IOT_BRIDGE: Decimal("0.3"),
    ServiceCategory.TELEMETRY_PM: Decimal("0.15"),
    ServiceCategory.MEDIA_ENGINE: Decimal("0.08"),
    ServiceCategory.AGENT_COMMS: Decimal("0.2"),
    ServiceCategory.CONTENT_FACTORY: Decimal("8.0"),
    ServiceCategory.RED_TEAM: Decimal("15.0"),
    ServiceCategory.ORACLE: Decimal("4.0"),
    ServiceCategory.PLATFORM_FEE: Decimal("0.01"),
    ServiceCategory.SWARM_DELEGATION: Decimal("0.5"),
    ServiceCategory.PROTOCOL_GEN: Decimal("30.0"),
    ServiceCategory.SANDBOX: Decimal("25.0"),
    ServiceCategory.RTAAS: Decimal("15.0"),
}

# Fiat → credits exchange rate
EXCHANGE_RATE = Decimal("1000.0")  # 1000 credits per $1 USD


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InsufficientFundsError(Exception):
    """Raised when a wallet has insufficient funds for a transaction."""
    def __init__(self, wallet_id: str, current: Decimal, required: Decimal):
        self.wallet_id = wallet_id
        self.current_balance = current
        self.required_amount = required
        self.shortfall = required - current
        super().__init__(f"Insufficient funds: {current} < {required}")


class WalletNotFoundError(Exception):
    """Raised when a wallet is not found."""
    def __init__(self, wallet_id: str):
        self.wallet_id = wallet_id
        super().__init__(f"Wallet not found: {wallet_id}")


class KYCVerificationRequiredError(Exception):
    """Raised when KYC verification is required but not completed."""
    def __init__(self, wallet_id: str, kyc_status: str):
        self.wallet_id = wallet_id
        self.kyc_status = kyc_status
        super().__init__(
            f"KYC verification required for wallet {wallet_id}. "
            f"Current status: {kyc_status}. Complete verification at /v1/kyc/sessions"
        )


# ---------------------------------------------------------------------------
# Agent Money Engine
# ---------------------------------------------------------------------------

class AgentMoney:
    """
    Top-level orchestrator for Agent Financial Gateways.

    Uses SQLModel with PostgreSQL for ACID-compliant transactions.
    All monetary operations use Decimal for precision.

    Operations:
    1. create_sponsor_wallet()  — Human liability sink account
    2. create_agent_wallet()    — Pre-paid machine wallet
    3. charge()                 — Per-action micro-debit with arbitrage
    4. top_up()                 — Fiat → credits conversion
    5. transfer()               — Sponsor → agent provisioning
    6. get_arbitrage_report()   — Profitability analytics
    """

    def __init__(self):
        self._session_factory = get_session_factory
        self._state = get_durable_state()

    async def _get_session(self) -> AsyncSession:
        """Get a database session."""
        return self._session_factory()

    # --- Wallet Management ---

    async def create_sponsor_wallet(
        self,
        sponsor_name: str,
        email: str,
        initial_credits: Decimal = Decimal("0"),
        currency: str = "USD",
        metadata: dict | None = None,
        owner_key: str = "",
        require_kyc: bool | None = None,
    ) -> WalletResponse:
        """Create a human sponsor (liability sink) root wallet."""
        kyc_required = require_kyc if require_kyc is not None else settings.KYC_REQUIRED_FOR_TOPUP

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
                    owner_key=owner_key,
                    metadata_json=_metadata_to_json(metadata),
                    kyc_status=KYCStatus.PENDING.value if kyc_required else KYCStatus.NOT_REQUIRED.value,
                    status="pending_kyc" if kyc_required else "active",
                )
                session.add(wallet)

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
        owner_key: str = "",
    ) -> WalletResponse:
        """Provision a pre-paid agent wallet from a sponsor's balance."""
        async with self._session_factory()() as session:
            async with session.begin():
                # Lock sponsor wallet for update
                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == sponsor_wallet_id)
                    .with_for_update()
                )
                sponsor = result.scalar_one_or_none()

                if not sponsor:
                    raise WalletNotFoundError(sponsor_wallet_id)
                if sponsor.wallet_type != WalletType.SPONSOR.value:
                    raise ValueError("Can only provision agent wallets from sponsor wallets")
                if sponsor.balance < budget_credits:
                    raise InsufficientFundsError(sponsor_wallet_id, sponsor.balance, budget_credits)

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
                    owner_key=owner_key,
                    parent_wallet_id=sponsor_wallet_id,
                    agent_id=agent_id,
                    daily_limit=daily_limit,
                    auto_refill=auto_refill,
                    auto_refill_threshold=auto_refill_threshold,
                    auto_refill_amount=auto_refill_amount,
                )
                session.add(agent_wallet)

                # Ledger entries
                session.add(LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=sponsor_wallet_id,
                    action=LedgerAction.TRANSFER.value,
                    amount=-budget_credits,
                    balance_after=sponsor.balance,
                    description=f"Provision agent wallet {agent_wallet_id} for {agent_id}",
                ))
                session.add(LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=agent_wallet_id,
                    action=LedgerAction.TRANSFER.value,
                    amount=budget_credits,
                    balance_after=budget_credits,
                    description=f"Provisioned from sponsor {sponsor_wallet_id}",
                ))

            await session.commit()
            logger.info(f"Created agent wallet {agent_wallet_id} with {budget_credits} credits")
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
        owner_key: str = "",
    ) -> WalletResponse:
        """Spawn a child sub-agent wallet from a parent agent's balance."""
        async with self._session_factory()() as session:
            async with session.begin():
                # Lock parent wallet
                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == parent_wallet_id)
                    .with_for_update()
                )
                parent = result.scalar_one_or_none()

                if not parent:
                    raise WalletNotFoundError(parent_wallet_id)
                if parent.wallet_type not in (WalletType.AGENT.value, WalletType.CHILD.value):
                    raise ValueError("Only agent or child wallets can spawn child wallets")
                if parent.balance < budget_credits:
                    raise InsufficientFundsError(parent_wallet_id, parent.balance, budget_credits)

                # Deduct from parent
                parent.balance -= budget_credits
                parent.lifetime_debits += budget_credits

                # Create child wallet
                child_wallet_id = f"chd-{uuid.uuid4().hex[:12]}"
                child = WalletModel(
                    wallet_id=child_wallet_id,
                    wallet_type=WalletType.CHILD.value,
                    owner_name=f"Child: {child_agent_id}",
                    owner_key=owner_key,
                    balance=budget_credits,
                    lifetime_credits=budget_credits,
                    parent_wallet_id=parent_wallet_id,
                    child_agent_id=child_agent_id,
                    max_spend=max_spend,
                    task_description=task_description,
                    ttl_seconds=ttl_seconds,
                )
                session.add(child)

                # Ledger entries
                session.add(LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=parent_wallet_id,
                    action=LedgerAction.TRANSFER.value,
                    amount=-budget_credits,
                    balance_after=parent.balance,
                    description=f"Delegate to child wallet {child_wallet_id} ({child_agent_id})",
                ))
                session.add(LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=child_wallet_id,
                    action=LedgerAction.TRANSFER.value,
                    amount=budget_credits,
                    balance_after=budget_credits,
                    description=f"Provisioned from parent {parent_wallet_id}",
                ))

            await session.commit()
            logger.info(f"Spawned child wallet {child_wallet_id} for {child_agent_id}")
            return wallet_model_to_response(child)

    async def reclaim_child_wallet(self, child_wallet_id: str) -> dict:
        """Reclaim unspent credits from a child wallet back to its parent."""
        async with self._session_factory()() as session:
            async with session.begin():
                # Lock both wallets
                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == child_wallet_id)
                    .with_for_update()
                )
                child = result.scalar_one_or_none()

                if not child:
                    raise WalletNotFoundError(child_wallet_id)
                if child.wallet_type != WalletType.CHILD.value:
                    raise ValueError("Can only reclaim from child wallets")
                if child.status == WalletStatus.CLOSED.value:
                    raise ValueError("Wallet already closed")

                # Get parent
                if not child.parent_wallet_id:
                    raise ValueError("Child wallet has no parent")

                parent_result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == child.parent_wallet_id)
                    .with_for_update()
                )
                parent = parent_result.scalar_one_or_none()

                if not parent:
                    raise WalletNotFoundError(child.parent_wallet_id)

                reclaim_amount = child.balance

                if reclaim_amount > Decimal("0"):
                    child.balance = Decimal("0")
                    parent.balance += reclaim_amount
                    parent.lifetime_credits += reclaim_amount

                    # Ledger entries
                    session.add(LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=child_wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=-reclaim_amount,
                        balance_after=Decimal("0"),
                        description=f"Reclaimed to parent {parent.wallet_id}",
                    ))
                    session.add(LedgerEntryModel(
                        entry_id=str(uuid.uuid4()),
                        wallet_id=parent.wallet_id,
                        action=LedgerAction.TRANSFER.value,
                        amount=reclaim_amount,
                        balance_after=parent.balance,
                        description=f"Reclaimed from child {child_wallet_id}",
                    ))

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
                # Lock both wallets in consistent order (alphabetical) to prevent deadlocks
                wallet_ids = sorted([from_wallet_id, to_wallet_id])

                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id.in_(wallet_ids))
                    .with_for_update()
                )
                wallets = {w.wallet_id: w for w in result.scalars().all()}

                source = wallets.get(from_wallet_id)
                dest = wallets.get(to_wallet_id)

                if not source:
                    raise WalletNotFoundError(from_wallet_id)
                if not dest:
                    raise WalletNotFoundError(to_wallet_id)

                if source.balance < amount:
                    raise InsufficientFundsError(from_wallet_id, source.balance, amount)

                # Execute transfer
                source.balance -= amount
                source.lifetime_debits += amount
                dest.balance += amount
                dest.lifetime_credits += amount

                # Create ledger entries on both sides
                session.add(LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=from_wallet_id,
                    action=LedgerAction.TRANSFER.value,
                    amount=-amount,
                    balance_after=source.balance,
                    description=description or f"Transfer to {to_wallet_id}",
                    correlation_id=correlation_id,
                ))
                session.add(LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=to_wallet_id,
                    action=LedgerAction.TRANSFER.value,
                    amount=amount,
                    balance_after=dest.balance,
                    description=description or f"Transfer from {from_wallet_id}",
                    correlation_id=correlation_id,
                ))

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
                select(WalletModel).where(WalletModel.wallet_id == parent_wallet_id)
            )
            parent = parent_result.scalar_one_or_none()

            if not parent:
                raise WalletNotFoundError(parent_wallet_id)

            # Get children
            children_result = await session.execute(
                select(WalletModel).where(WalletModel.parent_wallet_id == parent_wallet_id)
            )
            children = list(children_result.scalars().all())

            total_delegated = sum(w.lifetime_credits for w in children)
            total_reclaimed = sum(
                w.lifetime_credits - w.balance - w.lifetime_debits
                for w in children if w.status == WalletStatus.CLOSED.value
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
                "children": [
                    wallet_model_to_response(w)
                    for w in children
                ],
            }

    async def _dry_run_charge(
        self,
        wallet_id: str,
        service_category: ServiceCategory,
        units: Decimal,
        charge_amount: Decimal,
        description: str,
        session_id: str | None,
    ) -> SimulatedChargeResult:
        """
        Simulate a charge without affecting real balance or velocity.

        This is a dry-run operation that:
        - Does NOT record to the real ledger
        - Does NOT trigger velocity monitoring
        - Returns cost estimate with virtual balance impact

        If session_id is provided, uses the shadow ledger for stateful tracking.
        If session_id is None, returns a single-shot estimate based on real balance.
        """
        if session_id:
            shadow_ledger = get_shadow_ledger()
            try:
                result = await shadow_ledger.simulate_charge(
                    session_id=session_id,
                    service_category=service_category,
                    units=float(units),
                    description=description,
                )
                return result
            except ValueError as e:
                if "Session not found" in str(e):
                    raise ValueError(f"Dry-run session not found: {session_id}")
                raise

        wallet = await self.get_wallet(wallet_id)
        if not wallet:
            raise WalletNotFoundError(wallet_id)

        return SimulatedChargeResult(
            session_id=session_id or "",
            wallet_id=wallet_id,
            service_category=service_category.value,
            units=float(units),
            credits_would_charge=charge_amount,
            simulated_balance_before=float(wallet.balance),
            simulated_balance_after=float(wallet.balance) - float(charge_amount),
            would_succeed=wallet.balance >= charge_amount,
            reason=None if wallet.balance >= charge_amount else "insufficient_simulated_funds",
            dry_run=True,
        )

    # --- Micro-Metering & Charging ---

    async def charge(
        self,
        wallet_id: str,
        service_category: ServiceCategory,
        units: Decimal = Decimal("1"),
        request_path: str | None = None,
        description: str = "",
        dry_run: bool = False,
        dry_run_session_id: str | None = None,
    ) -> LedgerEntry | InsufficientFundsResponse | SimulatedChargeResult:
        """
        Charge an agent wallet for API usage with ACID transaction.

        Uses SELECT ... FOR UPDATE to lock the wallet row during the transaction.
        Also checks spend velocity and auto-freezes on anomalous patterns.

        If dry_run=True, simulates the charge without affecting real balance
        or triggering velocity monitoring. Uses the shadow ledger for tracking.
        """
        pricing = DEFAULT_PRICING.get(service_category)
        if not pricing:
            raise ValueError(f"No pricing for {service_category.value}")

        unit_name, credits_per_unit, _ = pricing
        charge_amount = units * credits_per_unit

        if dry_run:
            return await self._dry_run_charge(
                wallet_id=wallet_id,
                service_category=service_category,
                units=units,
                charge_amount=charge_amount,
                description=description or f"{units} × {unit_name}",
                session_id=dry_run_session_id,
            )

        compute_cost = units * COMPUTE_COSTS.get(service_category, Decimal("0"))
        margin = charge_amount - compute_cost

        velocity_monitor = get_velocity_monitor()
        velocity_result = await velocity_monitor.check_and_record_charge(wallet_id, charge_amount)

        if velocity_result.should_freeze:
            raise WalletFrozenError(wallet_id, velocity_result.reason)

        async with self._session_factory()() as session:
            async with session.begin():
                # Lock wallet row
                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == wallet_id)
                    .with_for_update()
                )
                wallet = result.scalar_one_or_none()

                if not wallet:
                    raise WalletNotFoundError(wallet_id)

                # Check child wallet lifetime spend cap
                if wallet.wallet_type == WalletType.CHILD.value and wallet.max_spend:
                    new_debits = wallet.lifetime_debits + charge_amount
                    if new_debits > wallet.max_spend:
                        shortfall = charge_amount - (wallet.max_spend - wallet.lifetime_debits)
                        return InsufficientFundsResponse(
                            wallet_id=wallet_id,
                            current_balance=wallet.balance,
                            required_amount=charge_amount,
                            shortfall=shortfall,
                            top_up_url=f"/v1/billing/top-up?wallet_id={wallet_id}&amount={charge_amount}",
                            message="Child wallet lifetime spend cap exceeded.",
                        )

                # Check daily limit
                today = datetime.now(timezone.utc).date()
                if wallet.daily_reset_at and wallet.daily_reset_at.date() != today:
                    wallet.daily_spent = Decimal("0")
                    wallet.daily_reset_at = datetime.now(timezone.utc)

                if wallet.daily_limit:
                    if wallet.daily_spent + charge_amount > wallet.daily_limit:
                        shortfall = charge_amount - (wallet.daily_limit - wallet.daily_spent)
                        return InsufficientFundsResponse(
                            wallet_id=wallet_id,
                            current_balance=wallet.balance,
                            required_amount=charge_amount,
                            shortfall=shortfall,
                            top_up_url=f"/v1/billing/top-up?wallet_id={wallet_id}&amount={charge_amount}",
                            message="Daily spending limit exceeded.",
                        )

                # Check balance
                if wallet.balance < charge_amount:
                    return InsufficientFundsResponse(
                        wallet_id=wallet_id,
                        current_balance=wallet.balance,
                        required_amount=charge_amount,
                        shortfall=charge_amount - wallet.balance,
                        top_up_url=f"/v1/billing/top-up?wallet_id={wallet_id}&amount={charge_amount}",
                    )

                # Execute debit
                wallet.balance -= charge_amount
                wallet.lifetime_debits += charge_amount
                wallet.daily_spent += charge_amount
                wallet.updated_at = datetime.now(timezone.utc)

                entry_id = str(uuid.uuid4())
                entry = LedgerEntryModel(
                    entry_id=entry_id,
                    wallet_id=wallet_id,
                    action=LedgerAction.DEBIT.value,
                    amount=-charge_amount,
                    balance_after=wallet.balance,
                    service_category=service_category.value,
                    description=description or f"{units} × {unit_name} @ {credits_per_unit} credits",
                    request_path=request_path,
                    compute_cost=compute_cost,
                    margin=margin,
                )
                session.add(entry)

                # Low balance alert
                if wallet.balance < (wallet.auto_refill_threshold or Decimal("100")):
                    alert = BillingAlertModel(
                        alert_id=str(uuid.uuid4())[:12],
                        wallet_id=wallet_id,
                        alert_type=AlertType.LOW_BALANCE.value,
                        current_balance=wallet.balance,
                        message=f"Wallet balance low: {wallet.balance} credits remaining.",
                        severity=AlertSeverity.WARNING.value,
                    )
                    session.add(alert)

            await session.commit()
            return ledger_entry_model_to_schema(entry)

    # --- Top-Up (Fiat Ingestion) ---

    async def top_up(
        self,
        wallet_id: str,
        amount_fiat: Decimal,
        payment_method: str = "stripe",
        payment_token: str | None = None,
    ) -> TopUpResponse:
        """Convert fiat currency to ecosystem credits with ACID transaction."""
        async with self._session_factory()() as session:
            async with session.begin():
                result = await session.execute(
                    select(WalletModel)
                    .where(WalletModel.wallet_id == wallet_id)
                    .with_for_update()
                )
                wallet = result.scalar_one_or_none()

                if not wallet:
                    raise WalletNotFoundError(wallet_id)
                if wallet.wallet_type != WalletType.SPONSOR.value:
                    raise ValueError("Top-ups only allowed on sponsor wallets")

                if settings.KYC_REQUIRED_FOR_TOPUP and wallet.kyc_status != KYCStatus.VERIFIED.value:
                    raise KYCVerificationRequiredError(wallet_id, wallet.kyc_status or "unknown")

                credits = amount_fiat * EXCHANGE_RATE
                top_up_id = str(uuid.uuid4())[:12]

                wallet.balance += credits
                wallet.lifetime_credits += credits
                wallet.updated_at = datetime.now(timezone.utc)

                entry = LedgerEntryModel(
                    entry_id=str(uuid.uuid4()),
                    wallet_id=wallet_id,
                    action=LedgerAction.CREDIT.value,
                    amount=credits,
                    balance_after=wallet.balance,
                    description=f"Top-up: ${amount_fiat} → {credits} credits",
                    metadata_json=f'{{"payment_method": "{payment_method}", "fiat_amount": "{amount_fiat}"}}',
                )
                session.add(entry)

            await session.commit()

            return TopUpResponse(
                top_up_id=top_up_id,
                wallet_id=wallet_id,
                amount_fiat=amount_fiat,
                credits_added=credits,
                exchange_rate=EXCHANGE_RATE,
                status=TopUpStatus.COMPLETED,
            )

    # --- Arbitrage Reporting ---

    async def get_arbitrage_report(self) -> ArbitrageReport:
        """Compute swarm arbitrage profitability across all services."""
        async with self._session_factory()() as session:
            result = await session.execute(
                select(LedgerEntryModel).where(
                    LedgerEntryModel.action == LedgerAction.DEBIT.value
                )
            )
            entries = list(result.scalars().all())

            total_revenue = Decimal("0")
            total_cost = Decimal("0")
            by_service: dict[str, dict] = {}

            for entry in entries:
                charge = abs(entry.amount)
                cost = entry.compute_cost or Decimal("0")
                margin = entry.margin or Decimal("0")

                total_revenue += charge
                total_cost += cost

                cat = entry.service_category or "unknown"
                if cat not in by_service:
                    by_service[cat] = {"revenue": Decimal("0"), "cost": Decimal("0"), "margin": Decimal("0"), "transactions": 0}
                by_service[cat]["revenue"] += charge
                by_service[cat]["cost"] += cost
                by_service[cat]["margin"] += margin
                by_service[cat]["transactions"] += 1

            # Compute percentages
            for cat_data in by_service.values():
                rev = cat_data["revenue"]
                cat_data["margin_pct"] = (cat_data["margin"] / rev * Decimal("100")) if rev > 0 else Decimal("0")

            gross_margin = total_revenue - total_cost
            margin_pct = (gross_margin / total_revenue * Decimal("100")) if total_revenue > 0 else Decimal("0")

            # Top profitable actions
            top_actions = sorted(entries, key=lambda e: e.margin or Decimal("0"), reverse=True)[:5]

            now = datetime.now(timezone.utc)

            return ArbitrageReport(
                period=f"{(now.replace(hour=0, minute=0, second=0) - __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}",
                total_revenue=total_revenue,
                total_compute_cost=total_cost,
                gross_margin=gross_margin,
                margin_percentage=margin_pct,
                by_service=by_service,
                top_profitable_actions=[
                    {
                        "entry_id": e.entry_id,
                        "service": e.service_category or "unknown",
                        "charge": abs(e.amount),
                        "cost": e.compute_cost or Decimal("0"),
                        "margin": e.margin or Decimal("0"),
                        "path": e.request_path,
                    }
                    for e in top_actions
                ],
            )

    # --- Pricing ---

    def get_pricing_table(self) -> list[ServicePricing]:
        """Return the full pricing table."""
        return [
            ServicePricing(
                service_category=cat,
                unit=unit,
                credits_per_unit=price,
                description=desc,
            )
            for cat, (unit, price, desc) in DEFAULT_PRICING.items()
        ]

    # --- Alerts ---

    async def get_alerts(self, wallet_id: str | None = None) -> list[BillingAlert]:
        """Get billing alerts."""
        async with self._session_factory()() as session:
            if wallet_id:
                result = await session.execute(
                    select(BillingAlertModel).where(
                        BillingAlertModel.wallet_id == wallet_id
                    ).order_by(BillingAlertModel.created_at.desc())
                )
            else:
                result = await session.execute(
                    select(BillingAlertModel).order_by(
                        BillingAlertModel.created_at.desc()
                    )
                )
            alerts = list(result.scalars().all())
            return [billing_alert_model_to_schema(a) for a in alerts]

    # --- Wallet Queries ---

    async def get_wallet(self, wallet_id: str) -> WalletResponse | None:
        """Get a wallet by ID."""
        async with self._session_factory()() as session:
            result = await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )
            wallet = result.scalar_one_or_none()
            if wallet:
                return wallet_model_to_response(wallet)
            return None

    async def list_wallets(
        self,
        wallet_type: str | None = None,
        owner_key: str | None = None,
    ) -> list[WalletResponse]:
        """List wallets with optional filtering."""
        async with self._session_factory()() as session:
            query = select(WalletModel)
            if wallet_type:
                enum_val = WalletType(wallet_type).value if wallet_type else None
                if enum_val:
                    query = query.where(WalletModel.wallet_type == enum_val)
            if owner_key:
                query = query.where(WalletModel.owner_key == owner_key)

            result = await session.execute(query)
            wallets = list(result.scalars().all())
            return [wallet_model_to_response(w) for w in wallets]

    async def get_ledger(self, wallet_id: str, limit: int = 50) -> list[LedgerEntry]:
        """Get ledger entries for a wallet."""
        async with self._session_factory()() as session:
            result = await session.execute(
                select(LedgerEntryModel)
                .where(LedgerEntryModel.wallet_id == wallet_id)
                .order_by(LedgerEntryModel.timestamp.desc())
                .limit(limit)
            )
            entries = list(result.scalars().all())
            return [ledger_entry_model_to_schema(e) for e in entries]

    # --- Service Registry ---

    async def register_service(
        self,
        owner_key: str,
        name: str,
        description: str,
        category: ServiceCategory,
        credits_per_unit: Decimal,
        unit_name: str = "request",
        mcp_manifest: dict | None = None,
    ) -> ServiceRegistration:
        """Register a billable service in the marketplace."""
        service_id = f"svc-{uuid.uuid4().hex[:12]}"

        async with self._session_factory()() as session:
            service = ServiceRegistryModel(
                service_id=service_id,
                name=name,
                description=description,
                owner_key=owner_key,
                category=category.value,
                credits_per_unit=credits_per_unit,
                unit_name=unit_name,
                mcp_manifest=json.dumps(mcp_manifest) if mcp_manifest else None,
                is_active=True,
            )
            session.add(service)
            await session.commit()

        logger.info(f"Registered service {service_id}: {name}")

        return ServiceRegistration(
            service_id=service_id,
            name=name,
            description=description,
            owner_wallet_id="",  # Will be populated when wallet is linked
            category=category,
            credits_per_unit=credits_per_unit,
            unit_name=unit_name,
            mcp_manifest=mcp_manifest,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )

    async def list_services(
        self,
        category: ServiceCategory | None = None,
        active_only: bool = True,
    ) -> list[ServiceRegistration]:
        """List services in the marketplace."""
        async with self._session_factory()() as session:
            query = select(ServiceRegistryModel)
            if category:
                query = query.where(ServiceRegistryModel.category == category.value)
            if active_only:
                query = query.where(ServiceRegistryModel.is_active.is_(True))

            result = await session.execute(query)
            services = result.scalars().all()

            return [
                ServiceRegistration(
                    service_id=s.service_id,
                    name=s.name,
                    description=s.description,
                    owner_wallet_id=s.owner_wallet_id,
                    category=ServiceCategory(s.category),
                    credits_per_unit=s.credits_per_unit,
                    unit_name=s.unit_name,
                    mcp_manifest=json.loads(s.mcp_manifest) if s.mcp_manifest else None,
                    is_active=s.is_active,
                    created_at=s.created_at,
                )
                for s in services
            ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metadata_to_json(metadata: dict | None) -> str | None:
    """Convert metadata dict to JSON string."""
    if not metadata:
        return None
    return json.dumps(metadata, default=str)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_agent_money: AgentMoney | None = None


def get_agent_money() -> AgentMoney:
    """Get or create the AgentMoney singleton."""
    global _agent_money
    if _agent_money is None:
        _agent_money = AgentMoney()
    return _agent_money
