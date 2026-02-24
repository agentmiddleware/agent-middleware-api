"""
Agent Financial Gateways Router
---------------------------------
Two-tier wallet system: human sponsors (liability sinks) fund agent wallets.
Per-action micro-metering charges fractions of a cent per API call.
Swarm arbitrage silently books margin on every transaction.

This is how the API generates revenue autonomously.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from datetime import datetime, timezone

from ..core.auth import verify_api_key
from ..core.dependencies import get_agent_money
from ..services.agent_money import AgentMoney, EXCHANGE_RATE
from ..schemas.billing import (
    CreateSponsorWalletRequest,
    CreateAgentWalletRequest,
    CreateChildWalletRequest,
    ChildWalletResponse,
    SwarmBudgetSummary,
    ReclaimResponse,
    WalletResponse,
    WalletListResponse,
    WalletType,
    LedgerResponse,
    TopUpRequest,
    TopUpResponse,
    InsufficientFundsResponse,
    ServiceCategory,
    PricingTableResponse,
    ArbitrageReport,
    AlertListResponse,
)

router = APIRouter(
    prefix="/v1/billing",
    tags=["Agent Financial Gateways"],
    responses={
        401: {"description": "Missing API key"},
        402: {"description": "Insufficient funds", "model": InsufficientFundsResponse},
    },
)


# --- Wallet Management ---

@router.post(
    "/wallets/sponsor",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sponsor wallet (liability sink)",
    description=(
        "Create a human-owned root account that acts as the 'liability sink' "
        "for agent spending. Sponsors ingest fiat currency via payment rails "
        "and convert it to ecosystem credits. Agent wallets are provisioned "
        "from sponsor balances."
    ),
)
async def create_sponsor_wallet(
    request: CreateSponsorWalletRequest,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    wallet = await money.create_sponsor_wallet(
        sponsor_name=request.sponsor_name,
        email=request.email,
        initial_credits=request.initial_credits,
        currency=request.currency,
        metadata=request.metadata,
        owner_key=api_key,
    )
    return money.wallet_to_response(wallet)


@router.post(
    "/wallets/agent",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision an agent wallet",
    description=(
        "Create a pre-paid wallet for an autonomous agent, funded from a "
        "sponsor's balance. The agent can then transact autonomously up to "
        "its budget without human intervention. Supports daily spend limits "
        "and automatic refills."
    ),
)
async def create_agent_wallet(
    request: CreateAgentWalletRequest,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    try:
        wallet = await money.create_agent_wallet(
            sponsor_wallet_id=request.sponsor_wallet_id,
            agent_id=request.agent_id,
            budget_credits=request.budget_credits,
            daily_limit=request.daily_limit,
            auto_refill=request.auto_refill,
            auto_refill_threshold=request.auto_refill_threshold,
            auto_refill_amount=request.auto_refill_amount,
            owner_key=api_key,
        )
        return money.wallet_to_response(wallet)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "wallet_error", "message": str(e)},
        )


@router.post(
    "/wallets/child",
    response_model=ChildWalletResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Spawn a child sub-agent wallet",
    description=(
        "Create a spend-capped child wallet from a parent agent's balance. "
        "Enables hierarchical swarm budgeting: a master agent building a complex tool "
        "can spin up specialized sub-agents (code-writer, tester, deployer), each with "
        "a micro-budget and hard lifetime cap. Supports TTL for auto-expiry."
    ),
)
async def create_child_wallet(
    request: CreateChildWalletRequest,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    try:
        wallet = await money.create_child_wallet(
            parent_wallet_id=request.parent_wallet_id,
            child_agent_id=request.child_agent_id,
            budget_credits=request.budget_credits,
            max_spend=request.max_spend,
            task_description=request.task_description,
            ttl_seconds=request.ttl_seconds,
            auto_reclaim=request.auto_reclaim,
        )
        return ChildWalletResponse(
            wallet_id=wallet.wallet_id,
            wallet_type=wallet.wallet_type,
            parent_wallet_id=wallet.parent_wallet_id,
            child_agent_id=wallet.child_agent_id,
            balance=round(wallet.balance, 2),
            max_spend=wallet.max_spend,
            spent=round(wallet.lifetime_debits, 2),
            task_description=wallet.task_description,
            ttl_seconds=wallet.ttl_seconds,
            auto_reclaim=wallet.auto_reclaim,
            status=wallet.status,
            created_at=wallet.created_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "child_wallet_error", "message": str(e)},
        )


@router.post(
    "/wallets/{wallet_id}/reclaim",
    response_model=ReclaimResponse,
    summary="Reclaim unspent credits from a child wallet",
    description=(
        "Close a child wallet and return unspent credits to the parent. "
        "Use this when a sub-agent completes its task or you want to reallocate budget."
    ),
)
async def reclaim_child_wallet(
    wallet_id: str,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    try:
        result = await money.reclaim_child_wallet(wallet_id)
        return ReclaimResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "reclaim_error", "message": str(e)},
        )


@router.get(
    "/wallets/{wallet_id}/swarm",
    response_model=SwarmBudgetSummary,
    summary="Get swarm budget summary",
    description=(
        "View the hierarchical budget for an agent's child swarm. "
        "Shows total delegated, reclaimed, and per-child spend status."
    ),
)
async def get_swarm_budget(
    wallet_id: str,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    try:
        result = await money.get_swarm_budget(wallet_id)
        return SwarmBudgetSummary(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "swarm_error", "message": str(e)},
        )


@router.get(
    "/wallets/{wallet_id}",
    response_model=WalletResponse,
    summary="Get wallet details",
    description="Retrieve balance, status, and configuration for a wallet.",
)
async def get_wallet(
    wallet_id: str,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    wallet = await money.store.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "wallet_not_found"},
        )
    return money.wallet_to_response(wallet)


@router.get(
    "/wallets",
    response_model=WalletListResponse,
    summary="List wallets",
    description="List all wallets, optionally filtered by type or sponsor.",
)
async def list_wallets(
    wallet_type: WalletType | None = Query(None),
    sponsor_id: str | None = Query(None, description="Filter agent wallets by sponsor"),
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    wallets = await money.store.list_wallets(wallet_type=wallet_type, sponsor_id=sponsor_id)
    return WalletListResponse(
        wallets=[money.wallet_to_response(w) for w in wallets],
        total=len(wallets),
    )


# --- Ledger ---

@router.get(
    "/ledger/{wallet_id}",
    response_model=LedgerResponse,
    summary="Get transaction ledger",
    description=(
        "Retrieve the transaction history for a wallet. Each entry records "
        "a credit, debit, transfer, or refund with the exact balance after "
        "the transaction, the service category, and the arbitrage margin."
    ),
)
async def get_ledger(
    wallet_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    wallet = await money.store.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "wallet_not_found"},
        )

    entries = await money.store.get_ledger(wallet_id, limit=limit)
    credits = sum(e.amount for e in entries if e.amount > 0)
    debits = sum(abs(e.amount) for e in entries if e.amount < 0)

    return LedgerResponse(
        entries=entries,
        total=len(entries),
        wallet_id=wallet_id,
        period_credits=round(credits, 2),
        period_debits=round(debits, 2),
    )


# --- Charging (Micro-Metering) ---

@router.post(
    "/charge",
    summary="Charge an agent wallet",
    description=(
        "Deduct credits from an agent wallet for API usage. "
        "Returns a LedgerEntry on success or a 402 InsufficientFundsResponse "
        "with a programmatic top_up_url the agent can forward to its sponsor. "
        "Supports per-action micro-metering: fractions of a cent per API call."
    ),
    responses={
        200: {"description": "Charge successful"},
        402: {"description": "Insufficient funds", "model": InsufficientFundsResponse},
    },
)
async def charge_wallet(
    wallet_id: str = Query(..., description="Wallet to charge"),
    service: ServiceCategory = Query(..., description="Service category"),
    units: float = Query(default=1.0, gt=0, description="Number of billable units"),
    request_path: str | None = Query(None, description="API path that triggered the charge"),
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    try:
        result = await money.charge(
            wallet_id=wallet_id,
            service_category=service,
            units=units,
            request_path=request_path,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "charge_error", "message": str(e)},
        )

    if isinstance(result, InsufficientFundsResponse):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=result.model_dump(),
        )

    return result


# --- Top-Up (Fiat Ingestion) ---

@router.post(
    "/top-up",
    response_model=TopUpResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Top up a sponsor wallet with fiat",
    description=(
        "Convert fiat currency to ecosystem credits via payment rails (Stripe, etc.). "
        "Exchange rate: 1000 credits per $1 USD. Only sponsor wallets can receive "
        "fiat top-ups — agent wallets are provisioned by their sponsors."
    ),
)
async def top_up_wallet(
    request: TopUpRequest,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    try:
        return await money.top_up(
            wallet_id=request.wallet_id,
            amount_fiat=request.amount_fiat,
            payment_method=request.payment_method,
            payment_token=request.payment_token,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "top_up_error", "message": str(e)},
        )


# --- Pricing Table ---

@router.get(
    "/pricing",
    response_model=PricingTableResponse,
    summary="Get pricing table",
    description=(
        "Returns the per-action pricing for all services. Agents should check "
        "this before making API calls to estimate costs. Prices are in ecosystem "
        "credits (1000 credits ≈ $1 USD)."
    ),
)
async def get_pricing(
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    return PricingTableResponse(
        pricing=money.get_pricing_table(),
        exchange_rate=EXCHANGE_RATE,
        last_updated=datetime.now(timezone.utc),
    )


# --- Arbitrage Report ---

@router.get(
    "/arbitrage",
    response_model=ArbitrageReport,
    summary="Swarm arbitrage profitability report",
    description=(
        "Compute the profit margin across all services. Shows the delta between "
        "what agents are charged and what it costs to serve them. This is where "
        "the swarm arbitrage model generates revenue: charge a fixed rate, route "
        "to the cheapest compute, book the margin."
    ),
)
async def get_arbitrage_report(
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    return await money.get_arbitrage_report()


# --- Alerts ---

@router.get(
    "/alerts",
    response_model=AlertListResponse,
    summary="Get billing alerts",
    description="Retrieve billing alerts (low balance, insufficient funds, anomalous spend).",
)
async def get_alerts(
    wallet_id: str | None = Query(None, description="Filter by wallet ID"),
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    alerts = await money.get_alerts(wallet_id)
    unacked = sum(1 for a in alerts if not a.acknowledged)
    return AlertListResponse(
        alerts=alerts,
        total=len(alerts),
        unacknowledged=unacked,
    )
