"""
Agent Financial Gateways — Service Layer
==========================================
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

Swarm Arbitrage: Charge fixed rate → route to cheapest compute → book margin.

Three-tier hierarchy (A2A extension):
┌─────────────────────────────────────────────┐
│ Sponsor (Liability Sink)                    │
│   └── Agent Wallet                          │
│         ├── Child Wallet (code-writer)      │
│         ├── Child Wallet (tester)           │
│         └── Child Wallet (deployer)         │
│              └── spend-capped, time-limited │
└─────────────────────────────────────────────┘

Production wiring:
- PostgreSQL for ACID-compliant ledger
- Redis for real-time balance caching
- Stripe SDK for fiat ingestion
- Kafka for async ledger events
"""

import asyncio
import uuid
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from ..core.durable_state import get_durable_state
from ..schemas.billing import (
    WalletType,
    WalletStatus,
    LedgerAction,
    ServiceCategory,
    TopUpStatus,
    AlertType,
    WalletResponse,
    LedgerEntry,
    TopUpResponse,
    InsufficientFundsResponse,
    ServicePricing,
    ArbitrageReport,
    BillingAlert,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing Table
# ---------------------------------------------------------------------------

# Credits per unit for each service. 1000 credits ≈ $1 USD.
DEFAULT_PRICING: dict[ServiceCategory, tuple[str, float, str]] = {
    # (unit, credits_per_unit, description)
    ServiceCategory.IOT_BRIDGE: ("request", 2.0, "Per IoT message bridged"),
    ServiceCategory.TELEMETRY_PM: ("event", 1.0, "Per telemetry event ingested"),
    ServiceCategory.MEDIA_ENGINE: ("frame", 0.5, "Per video frame processed"),
    ServiceCategory.AGENT_COMMS: ("message", 1.5, "Per agent message routed"),
    ServiceCategory.CONTENT_FACTORY: ("piece", 50.0, "Per content piece generated"),
    ServiceCategory.RED_TEAM: ("scan", 100.0, "Per security scan executed"),
    ServiceCategory.ORACLE: ("crawl", 25.0, "Per API crawled and indexed"),
    ServiceCategory.PLATFORM_FEE: ("request", 0.1, "Base platform fee per API call"),
    ServiceCategory.SWARM_DELEGATION: ("child", 5.0, "Per child wallet spawned"),
    ServiceCategory.PROTOCOL_GEN: ("generation", 200.0, "Per llm.txt + OpenAPI spec generated"),
    ServiceCategory.SANDBOX: ("session", 150.0, "Per sandbox environment session"),
    ServiceCategory.RTAAS: ("scan", 100.0, "Per external Red Team scan"),
}

# Internal compute costs (what it actually costs us to serve)
# The delta between charged price and compute cost = arbitrage margin
COMPUTE_COSTS: dict[ServiceCategory, float] = {
    ServiceCategory.IOT_BRIDGE: 0.3,
    ServiceCategory.TELEMETRY_PM: 0.15,
    ServiceCategory.MEDIA_ENGINE: 0.08,
    ServiceCategory.AGENT_COMMS: 0.2,
    ServiceCategory.CONTENT_FACTORY: 8.0,
    ServiceCategory.RED_TEAM: 15.0,
    ServiceCategory.ORACLE: 4.0,
    ServiceCategory.PLATFORM_FEE: 0.01,
    ServiceCategory.SWARM_DELEGATION: 0.5,
    ServiceCategory.PROTOCOL_GEN: 30.0,
    ServiceCategory.SANDBOX: 25.0,
    ServiceCategory.RTAAS: 15.0,
}

# Fiat → credits exchange rate
EXCHANGE_RATE = 1000.0  # 1000 credits per $1 USD


# ---------------------------------------------------------------------------
# Wallet Store
# ---------------------------------------------------------------------------

@dataclass
class Wallet:
    """Internal wallet representation."""
    wallet_id: str
    wallet_type: WalletType
    owner_name: str
    balance: float = 0.0
    lifetime_credits: float = 0.0
    lifetime_debits: float = 0.0
    status: WalletStatus = WalletStatus.ACTIVE
    daily_limit: float | None = None
    daily_spent: float = 0.0
    daily_reset_date: str = ""
    sponsor_wallet_id: str | None = None
    agent_id: str | None = None
    auto_refill: bool = False
    auto_refill_threshold: float = 100.0
    auto_refill_amount: float = 1000.0
    email: str = ""
    currency: str = "USD"
    owner_key: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    # --- Child wallet fields (Pillar 10: Swarm Delegation) ---
    parent_wallet_id: str | None = None  # For child wallets: the agent that spawned it
    child_agent_id: str | None = None    # Identifier for the child sub-agent
    max_spend: float | None = None       # Hard lifetime spend cap
    task_description: str = ""           # What the child agent is building
    ttl_seconds: int | None = None       # Auto-freeze timer
    auto_reclaim: bool = True            # Reclaim unspent on completion


class WalletStore:
    """Wallet and ledger store with optional Redis/PostgreSQL durability."""

    def __init__(self):
        self._wallets: dict[str, Wallet] = {}
        self._ledger: list[LedgerEntry] = []
        self._top_ups: dict[str, dict] = {}
        self._alerts: list[BillingAlert] = []
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._hydrated = False
        self._state = get_durable_state()

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _wallet_from_dict(cls, data: dict[str, Any]) -> Wallet:
        payload = dict(data)
        payload["wallet_type"] = WalletType(payload["wallet_type"])
        payload["status"] = WalletStatus(payload.get("status", WalletStatus.ACTIVE))
        parsed_created = cls._parse_dt(payload.get("created_at"))
        if parsed_created is not None:
            payload["created_at"] = parsed_created
        return Wallet(**payload)

    async def _hydrate_if_needed(self):
        if self._hydrated:
            return

        async with self._init_lock:
            if self._hydrated:
                return

            wallets_payload = await self._state.load_json("billing.wallets")
            if isinstance(wallets_payload, dict):
                loaded: dict[str, Wallet] = {}
                for wallet_id, wallet_data in wallets_payload.items():
                    try:
                        loaded[wallet_id] = self._wallet_from_dict(wallet_data)
                    except Exception:
                        logger.exception("Skipping corrupt wallet record: %s", wallet_id)
                self._wallets = loaded

            ledger_payload = await self._state.load_json("billing.ledger")
            if isinstance(ledger_payload, list):
                loaded_ledger: list[LedgerEntry] = []
                for entry in ledger_payload:
                    try:
                        loaded_ledger.append(LedgerEntry.model_validate(entry))
                    except Exception:
                        logger.exception("Skipping corrupt billing ledger entry")
                self._ledger = loaded_ledger

            alerts_payload = await self._state.load_json("billing.alerts")
            if isinstance(alerts_payload, list):
                loaded_alerts: list[BillingAlert] = []
                for alert in alerts_payload:
                    try:
                        loaded_alerts.append(BillingAlert.model_validate(alert))
                    except Exception:
                        logger.exception("Skipping corrupt billing alert")
                self._alerts = loaded_alerts

            topups_payload = await self._state.load_json("billing.topups")
            if isinstance(topups_payload, dict):
                self._top_ups = topups_payload

            self._hydrated = True

    async def _persist_locked(self):
        if not self._state.enabled:
            return

        await self._state.save_json(
            "billing.wallets",
            {wallet_id: asdict(wallet) for wallet_id, wallet in self._wallets.items()},
        )
        await self._state.save_json(
            "billing.ledger",
            [entry.model_dump(mode="json") for entry in self._ledger],
        )
        await self._state.save_json(
            "billing.alerts",
            [alert.model_dump(mode="json") for alert in self._alerts],
        )
        await self._state.save_json("billing.topups", self._top_ups)

    async def persist(self):
        await self._hydrate_if_needed()
        async with self._lock:
            await self._persist_locked()

    async def create_wallet(self, wallet: Wallet) -> Wallet:
        await self._hydrate_if_needed()
        async with self._lock:
            self._wallets[wallet.wallet_id] = wallet
            await self._persist_locked()
        return wallet

    async def get_wallet(self, wallet_id: str) -> Wallet | None:
        await self._hydrate_if_needed()
        return self._wallets.get(wallet_id)

    async def list_wallets(
        self,
        wallet_type: WalletType | None = None,
        sponsor_id: str | None = None,
    ) -> list[Wallet]:
        await self._hydrate_if_needed()
        wallets = list(self._wallets.values())
        if wallet_type:
            wallets = [w for w in wallets if w.wallet_type == wallet_type]
        if sponsor_id:
            wallets = [w for w in wallets if w.sponsor_wallet_id == sponsor_id]
        return wallets

    async def append_ledger(self, entry: LedgerEntry):
        await self._hydrate_if_needed()
        async with self._lock:
            self._ledger.append(entry)
            await self._persist_locked()

    async def get_ledger(
        self,
        wallet_id: str,
        limit: int = 50,
    ) -> list[LedgerEntry]:
        await self._hydrate_if_needed()
        entries = [e for e in self._ledger if e.wallet_id == wallet_id]
        return entries[-limit:]

    async def store_alert(self, alert: BillingAlert):
        await self._hydrate_if_needed()
        async with self._lock:
            self._alerts.append(alert)
            await self._persist_locked()

    async def get_alerts(self, wallet_id: str | None = None) -> list[BillingAlert]:
        await self._hydrate_if_needed()
        if wallet_id:
            return [a for a in self._alerts if a.wallet_id == wallet_id]
        return list(self._alerts)

    async def get_all_ledger_entries(self) -> list[LedgerEntry]:
        await self._hydrate_if_needed()
        return list(self._ledger)


# ---------------------------------------------------------------------------
# Agent Money Engine
# ---------------------------------------------------------------------------

class AgentMoney:
    """
    Top-level orchestrator for Agent Financial Gateways.

    Operations:
    1. create_sponsor_wallet()  — Human liability sink account
    2. create_agent_wallet()    — Pre-paid machine wallet
    3. charge()                 — Per-action micro-debit with arbitrage
    4. top_up()                 — Fiat → credits conversion
    5. transfer()               — Sponsor → agent provisioning
    6. get_arbitrage_report()   — Profitability analytics
    """

    def __init__(self):
        self.store = WalletStore()

    # --- Wallet Management ---

    async def create_sponsor_wallet(
        self,
        sponsor_name: str,
        email: str,
        initial_credits: float = 0.0,
        currency: str = "USD",
        metadata: dict | None = None,
        owner_key: str = "",
    ) -> Wallet:
        """Create a human sponsor (liability sink) root wallet."""
        wallet = Wallet(
            wallet_id=f"spn-{uuid.uuid4().hex[:12]}",
            wallet_type=WalletType.SPONSOR,
            owner_name=sponsor_name,
            balance=initial_credits,
            lifetime_credits=initial_credits,
            email=email,
            currency=currency,
            owner_key=owner_key,
            metadata=metadata or {},
        )
        await self.store.create_wallet(wallet)

        # Record initial credit if any
        if initial_credits > 0:
            entry = LedgerEntry(
                entry_id=str(uuid.uuid4()),
                wallet_id=wallet.wallet_id,
                action=LedgerAction.CREDIT,
                amount=initial_credits,
                balance_after=initial_credits,
                description="Initial sponsor deposit",
                timestamp=datetime.now(timezone.utc),
            )
            await self.store.append_ledger(entry)

        logger.info(f"Created sponsor wallet {wallet.wallet_id} for {sponsor_name}")
        return wallet

    async def create_agent_wallet(
        self,
        sponsor_wallet_id: str,
        agent_id: str,
        budget_credits: float,
        daily_limit: float | None = None,
        auto_refill: bool = False,
        auto_refill_threshold: float = 100.0,
        auto_refill_amount: float = 1000.0,
        owner_key: str = "",
    ) -> Wallet:
        """Provision a pre-paid agent wallet from a sponsor's balance."""
        sponsor = await self.store.get_wallet(sponsor_wallet_id)
        if not sponsor:
            raise ValueError(f"Sponsor wallet {sponsor_wallet_id} not found")
        if sponsor.wallet_type != WalletType.SPONSOR:
            raise ValueError("Can only provision agent wallets from sponsor wallets")
        if sponsor.balance < budget_credits:
            raise ValueError(
                f"Insufficient sponsor balance: {sponsor.balance} < {budget_credits}"
            )

        # Deduct from sponsor
        sponsor.balance -= budget_credits
        sponsor.lifetime_debits += budget_credits

        # Create agent wallet
        wallet = Wallet(
            wallet_id=f"agt-{uuid.uuid4().hex[:12]}",
            wallet_type=WalletType.AGENT,
            owner_name=f"Agent: {agent_id}",
            balance=budget_credits,
            lifetime_credits=budget_credits,
            sponsor_wallet_id=sponsor_wallet_id,
            agent_id=agent_id,
            daily_limit=daily_limit,
            auto_refill=auto_refill,
            auto_refill_threshold=auto_refill_threshold,
            auto_refill_amount=auto_refill_amount,
            owner_key=owner_key,
        )
        await self.store.create_wallet(wallet)

        # Ledger: sponsor transfer out
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=sponsor_wallet_id,
            action=LedgerAction.TRANSFER,
            amount=-budget_credits,
            balance_after=sponsor.balance,
            description=f"Provision agent wallet {wallet.wallet_id} for {agent_id}",
            timestamp=datetime.now(timezone.utc),
        ))

        # Ledger: agent transfer in
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=wallet.wallet_id,
            action=LedgerAction.TRANSFER,
            amount=budget_credits,
            balance_after=budget_credits,
            description=f"Provisioned from sponsor {sponsor_wallet_id}",
            timestamp=datetime.now(timezone.utc),
        ))

        logger.info(f"Created agent wallet {wallet.wallet_id} with {budget_credits} credits")
        return wallet

    # --- Child Wallet Management (Swarm Delegation) ---

    async def create_child_wallet(
        self,
        parent_wallet_id: str,
        child_agent_id: str,
        budget_credits: float,
        max_spend: float,
        task_description: str = "",
        ttl_seconds: int | None = None,
        auto_reclaim: bool = True,
    ) -> Wallet:
        """Spawn a child sub-agent wallet from a parent agent's balance.

        Enables hierarchical swarm budgeting: master agent → child wallets
        with hard spend caps and optional time-to-live.
        """
        parent = await self.store.get_wallet(parent_wallet_id)
        if not parent:
            raise ValueError(f"Parent wallet {parent_wallet_id} not found")
        if parent.wallet_type not in (WalletType.AGENT, WalletType.CHILD):
            raise ValueError("Only agent or child wallets can spawn child wallets")
        if parent.balance < budget_credits:
            raise ValueError(
                f"Insufficient parent balance: {parent.balance} < {budget_credits}"
            )

        # Deduct from parent
        parent.balance -= budget_credits
        parent.lifetime_debits += budget_credits

        child = Wallet(
            wallet_id=f"chd-{uuid.uuid4().hex[:12]}",
            wallet_type=WalletType.CHILD,
            owner_name=f"Child: {child_agent_id}",
            balance=budget_credits,
            lifetime_credits=budget_credits,
            parent_wallet_id=parent_wallet_id,
            child_agent_id=child_agent_id,
            sponsor_wallet_id=parent.sponsor_wallet_id or parent_wallet_id,
            max_spend=max_spend,
            task_description=task_description,
            ttl_seconds=ttl_seconds,
            auto_reclaim=auto_reclaim,
        )
        await self.store.create_wallet(child)

        # Ledger: parent transfer out
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=parent_wallet_id,
            action=LedgerAction.TRANSFER,
            amount=-budget_credits,
            balance_after=parent.balance,
            description=f"Delegate to child wallet {child.wallet_id} ({child_agent_id})",
            timestamp=datetime.now(timezone.utc),
        ))

        # Ledger: child transfer in
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=child.wallet_id,
            action=LedgerAction.TRANSFER,
            amount=budget_credits,
            balance_after=budget_credits,
            description=f"Provisioned from parent {parent_wallet_id}",
            timestamp=datetime.now(timezone.utc),
        ))

        logger.info(f"Spawned child wallet {child.wallet_id} for {child_agent_id} with {budget_credits} credits (cap: {max_spend})")
        return child

    async def reclaim_child_wallet(self, child_wallet_id: str) -> dict:
        """Reclaim unspent credits from a child wallet back to its parent."""
        child = await self.store.get_wallet(child_wallet_id)
        if not child:
            raise ValueError(f"Child wallet {child_wallet_id} not found")
        if child.wallet_type != WalletType.CHILD:
            raise ValueError("Can only reclaim from child wallets")
        if child.status in (WalletStatus.CLOSED,):
            raise ValueError("Wallet already closed")

        parent = await self.store.get_wallet(child.parent_wallet_id)
        if not parent:
            raise ValueError(f"Parent wallet {child.parent_wallet_id} not found")

        reclaim_amount = child.balance
        if reclaim_amount > 0:
            child.balance = 0
            parent.balance += reclaim_amount
            parent.lifetime_credits += reclaim_amount

            # Ledger: child reclaim out
            await self.store.append_ledger(LedgerEntry(
                entry_id=str(uuid.uuid4()),
                wallet_id=child_wallet_id,
                action=LedgerAction.TRANSFER,
                amount=-reclaim_amount,
                balance_after=0,
                description=f"Reclaimed to parent {parent.wallet_id}",
                timestamp=datetime.now(timezone.utc),
            ))

            # Ledger: parent reclaim in
            await self.store.append_ledger(LedgerEntry(
                entry_id=str(uuid.uuid4()),
                wallet_id=parent.wallet_id,
                action=LedgerAction.TRANSFER,
                amount=reclaim_amount,
                balance_after=parent.balance,
                description=f"Reclaimed from child {child_wallet_id}",
                timestamp=datetime.now(timezone.utc),
            ))

        child.status = WalletStatus.CLOSED
        await self.store.persist()

        return {
            "child_wallet_id": child_wallet_id,
            "parent_wallet_id": parent.wallet_id,
            "credits_reclaimed": round(reclaim_amount, 2),
            "parent_balance_after": round(parent.balance, 2),
            "child_status": child.status,
        }

    async def get_swarm_budget(self, parent_wallet_id: str) -> dict:
        """Get hierarchical budget summary for an agent's child swarm."""
        parent = await self.store.get_wallet(parent_wallet_id)
        if not parent:
            raise ValueError(f"Wallet {parent_wallet_id} not found")

        all_wallets = await self.store.list_wallets()
        children = [w for w in all_wallets if w.parent_wallet_id == parent_wallet_id]

        total_delegated = sum(w.lifetime_credits for w in children)
        total_reclaimed = sum(
            w.lifetime_credits - w.balance - w.lifetime_debits
            for w in children if w.status == WalletStatus.CLOSED
        )
        active = [w for w in children if w.status == WalletStatus.ACTIVE]
        completed = [w for w in children if w.status == WalletStatus.CLOSED]
        frozen = [w for w in children if w.status == WalletStatus.FROZEN]

        return {
            "parent_wallet_id": parent_wallet_id,
            "parent_balance": round(parent.balance, 2),
            "total_delegated": round(total_delegated, 2),
            "total_reclaimed": round(total_reclaimed, 2),
            "active_children": len(active),
            "completed_children": len(completed),
            "frozen_children": len(frozen),
            "children": [
                {
                    "wallet_id": w.wallet_id,
                    "wallet_type": w.wallet_type,
                    "parent_wallet_id": w.parent_wallet_id,
                    "child_agent_id": w.child_agent_id,
                    "balance": round(w.balance, 2),
                    "max_spend": w.max_spend,
                    "spent": round(w.lifetime_debits, 2),
                    "task_description": w.task_description,
                    "ttl_seconds": w.ttl_seconds,
                    "auto_reclaim": w.auto_reclaim,
                    "status": w.status,
                    "created_at": w.created_at,
                }
                for w in children
            ],
        }

    # --- Micro-Metering & Charging ---

    async def charge(
        self,
        wallet_id: str,
        service_category: ServiceCategory,
        units: float = 1.0,
        request_path: str | None = None,
        description: str = "",
    ) -> LedgerEntry | InsufficientFundsResponse:
        """
        Charge an agent wallet for API usage.

        Computes: charge = units × price_per_unit
        Books arbitrage margin: margin = charge - (units × compute_cost)

        Returns LedgerEntry on success, InsufficientFundsResponse on 402.
        """
        wallet = await self.store.get_wallet(wallet_id)
        if not wallet:
            raise ValueError(f"Wallet {wallet_id} not found")

        # Look up pricing
        pricing = DEFAULT_PRICING.get(service_category)
        if not pricing:
            raise ValueError(f"No pricing for {service_category.value}")

        unit_name, credits_per_unit, _ = pricing
        charge_amount = units * credits_per_unit
        compute_cost = units * COMPUTE_COSTS.get(service_category, 0)
        margin = charge_amount - compute_cost

        # Check child wallet lifetime spend cap
        if wallet.wallet_type == WalletType.CHILD and wallet.max_spend is not None:
            if (wallet.lifetime_debits + charge_amount) > wallet.max_spend:
                return InsufficientFundsResponse(
                    wallet_id=wallet_id,
                    current_balance=wallet.balance,
                    required_amount=charge_amount,
                    shortfall=charge_amount - (wallet.max_spend - wallet.lifetime_debits),
                    top_up_url=f"/v1/billing/top-up?wallet_id={wallet_id}&amount={charge_amount}",
                    message="Child wallet lifetime spend cap exceeded. Reclaim and re-provision.",
                )

        # Check daily limit
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if wallet.daily_reset_date != today:
            wallet.daily_spent = 0.0
            wallet.daily_reset_date = today

        if wallet.daily_limit and (wallet.daily_spent + charge_amount) > wallet.daily_limit:
            return InsufficientFundsResponse(
                wallet_id=wallet_id,
                current_balance=wallet.balance,
                required_amount=charge_amount,
                shortfall=charge_amount - (wallet.daily_limit - wallet.daily_spent),
                top_up_url=f"/v1/billing/top-up?wallet_id={wallet_id}&amount={charge_amount}",
                message="Daily spending limit exceeded. Contact sponsor to increase limit.",
            )

        # Check balance
        if wallet.balance < charge_amount:
            # Check auto-refill
            if wallet.auto_refill and wallet.sponsor_wallet_id:
                refilled = await self._auto_refill(wallet)
                if not refilled or wallet.balance < charge_amount:
                    return self._insufficient_funds(wallet, charge_amount)
            else:
                return self._insufficient_funds(wallet, charge_amount)

        # Execute debit
        wallet.balance -= charge_amount
        wallet.lifetime_debits += charge_amount
        wallet.daily_spent += charge_amount

        entry = LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=wallet_id,
            action=LedgerAction.DEBIT,
            amount=-charge_amount,
            balance_after=wallet.balance,
            service_category=service_category,
            description=description or f"{units} × {unit_name} @ {credits_per_unit} credits",
            request_path=request_path,
            compute_cost=round(compute_cost, 4),
            margin=round(margin, 4),
            timestamp=datetime.now(timezone.utc),
        )
        await self.store.append_ledger(entry)

        # Check for low balance alert
        if wallet.balance < (wallet.auto_refill_threshold if wallet.auto_refill else 100):
            await self._emit_alert(
                wallet, AlertType.LOW_BALANCE,
                f"Wallet balance low: {wallet.balance:.2f} credits remaining.",
            )

        return entry

    def _insufficient_funds(self, wallet: Wallet, required: float) -> InsufficientFundsResponse:
        """Build a 402 response."""
        return InsufficientFundsResponse(
            wallet_id=wallet.wallet_id,
            current_balance=wallet.balance,
            required_amount=required,
            shortfall=required - wallet.balance,
            top_up_url=f"/v1/billing/top-up?wallet_id={wallet.wallet_id}&amount={required}",
        )

    async def _auto_refill(self, wallet: Wallet) -> bool:
        """Attempt to auto-refill an agent wallet from its sponsor."""
        if not wallet.sponsor_wallet_id:
            return False

        sponsor = await self.store.get_wallet(wallet.sponsor_wallet_id)
        if not sponsor or sponsor.balance < wallet.auto_refill_amount:
            return False

        # Transfer from sponsor
        amount = wallet.auto_refill_amount
        sponsor.balance -= amount
        sponsor.lifetime_debits += amount
        wallet.balance += amount
        wallet.lifetime_credits += amount

        # Ledger entries
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=sponsor.wallet_id,
            action=LedgerAction.TRANSFER,
            amount=-amount,
            balance_after=sponsor.balance,
            description=f"Auto-refill to {wallet.wallet_id}",
            timestamp=datetime.now(timezone.utc),
        ))
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=wallet.wallet_id,
            action=LedgerAction.TRANSFER,
            amount=amount,
            balance_after=wallet.balance,
            description=f"Auto-refill from sponsor {sponsor.wallet_id}",
            timestamp=datetime.now(timezone.utc),
        ))

        logger.info(f"Auto-refilled {wallet.wallet_id} with {amount} credits")
        return True

    # --- Top-Up (Fiat Ingestion) ---

    async def top_up(
        self,
        wallet_id: str,
        amount_fiat: float,
        payment_method: str = "stripe",
        payment_token: str | None = None,
    ) -> TopUpResponse:
        """Convert fiat currency to ecosystem credits."""
        wallet = await self.store.get_wallet(wallet_id)
        if not wallet:
            raise ValueError(f"Wallet {wallet_id} not found")
        if wallet.wallet_type != WalletType.SPONSOR:
            raise ValueError("Top-ups only allowed on sponsor wallets. Agent wallets are provisioned by sponsors.")

        credits = amount_fiat * EXCHANGE_RATE

        # Simulate payment processing (production: Stripe API)
        wallet.balance += credits
        wallet.lifetime_credits += credits

        # Ledger
        await self.store.append_ledger(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            wallet_id=wallet_id,
            action=LedgerAction.CREDIT,
            amount=credits,
            balance_after=wallet.balance,
            description=f"Top-up: ${amount_fiat:.2f} {wallet.currency} → {credits:.0f} credits",
            timestamp=datetime.now(timezone.utc),
            metadata={"payment_method": payment_method, "fiat_amount": amount_fiat},
        ))

        return TopUpResponse(
            top_up_id=str(uuid.uuid4())[:12],
            wallet_id=wallet_id,
            amount_fiat=amount_fiat,
            credits_added=credits,
            exchange_rate=EXCHANGE_RATE,
            status=TopUpStatus.COMPLETED,
        )

    # --- Arbitrage Reporting ---

    async def get_arbitrage_report(self) -> ArbitrageReport:
        """Compute swarm arbitrage profitability across all services."""
        ledger = await self.store.get_all_ledger_entries()

        total_revenue = 0.0
        total_cost = 0.0
        by_service: dict[str, dict] = {}

        debit_entries = [e for e in ledger if e.action == LedgerAction.DEBIT]

        for entry in debit_entries:
            charge = abs(entry.amount)
            cost = entry.compute_cost or 0
            margin = entry.margin or 0

            total_revenue += charge
            total_cost += cost

            cat = entry.service_category.value if entry.service_category else "unknown"
            if cat not in by_service:
                by_service[cat] = {"revenue": 0, "cost": 0, "margin": 0, "transactions": 0}
            by_service[cat]["revenue"] += charge
            by_service[cat]["cost"] += cost
            by_service[cat]["margin"] += margin
            by_service[cat]["transactions"] += 1

        # Compute percentages
        for cat_data in by_service.values():
            rev = cat_data["revenue"]
            cat_data["margin_pct"] = round((cat_data["margin"] / rev * 100) if rev > 0 else 0, 1)

        gross_margin = total_revenue - total_cost
        margin_pct = (gross_margin / total_revenue * 100) if total_revenue > 0 else 0

        # Top profitable actions
        top_actions = sorted(debit_entries, key=lambda e: (e.margin or 0), reverse=True)[:5]

        now = datetime.now(timezone.utc)
        period = f"{(now - timedelta(days=1)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"

        return ArbitrageReport(
            period=period,
            total_revenue=round(total_revenue, 2),
            total_compute_cost=round(total_cost, 2),
            gross_margin=round(gross_margin, 2),
            margin_percentage=round(margin_pct, 1),
            by_service=by_service,
            top_profitable_actions=[
                {
                    "entry_id": e.entry_id,
                    "service": e.service_category.value if e.service_category else "unknown",
                    "charge": abs(e.amount),
                    "cost": e.compute_cost or 0,
                    "margin": e.margin or 0,
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

    async def _emit_alert(
        self,
        wallet: Wallet,
        alert_type: AlertType,
        message: str,
    ):
        alert = BillingAlert(
            alert_id=str(uuid.uuid4())[:12],
            alert_type=alert_type,
            wallet_id=wallet.wallet_id,
            message=message,
            current_value=wallet.balance,
            timestamp=datetime.now(timezone.utc),
        )
        await self.store.store_alert(alert)
        logger.warning(f"Billing alert [{alert_type.value}]: {message}")

    async def get_alerts(self, wallet_id: str | None = None) -> list[BillingAlert]:
        return await self.store.get_alerts(wallet_id)

    # --- Helpers ---

    def wallet_to_response(self, w: Wallet) -> WalletResponse:
        """Convert internal Wallet to API response."""
        return WalletResponse(
            wallet_id=w.wallet_id,
            wallet_type=w.wallet_type,
            owner_name=w.owner_name,
            balance=round(w.balance, 2),
            lifetime_credits=round(w.lifetime_credits, 2),
            lifetime_debits=round(w.lifetime_debits, 2),
            status=w.status,
            daily_limit=w.daily_limit,
            daily_spent=round(w.daily_spent, 2),
            sponsor_wallet_id=w.sponsor_wallet_id,
            agent_id=w.agent_id,
            auto_refill=w.auto_refill,
            created_at=w.created_at,
            metadata=w.metadata,
        )
