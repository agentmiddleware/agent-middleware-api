"""
Agent Financial Gateways Router
---------------------------------
Two-tier wallet system: human sponsors (liability sinks) fund agent wallets.
Per-action micro-metering charges fractions of a cent per API call.
Swarm arbitrage silently books margin on every transaction.

This is how the API generates revenue autonomously.
"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..core.auth import AuthContext, get_auth_context, verify_api_key
from ..core.dependencies import get_agent_money
from ..services.agent_money import (
    AgentMoney,
    EXCHANGE_RATE,
    InsufficientFundsError,
    WalletNotFoundError,
    KYCVerificationRequiredError,
)
from ..services.velocity_monitor import WalletFrozenError
from ..services.stripe_integration import get_stripe_integration
from ..services.shadow_ledger import get_shadow_ledger
from ..schemas.billing import (
    CreateSponsorWalletRequest,
    CreateAgentWalletRequest,
    CreateChildWalletRequest,
    ChildWalletResponse,
    SwarmBudgetSummary,
    ReclaimResponse,
    WalletResponse,
    WalletListResponse,
    LedgerResponse,
    TopUpRequest,
    TopUpResponse,
    InsufficientFundsResponse,
    ServiceCategory,
    PricingTableResponse,
    ArbitrageReport,
    AlertListResponse,
    RegisterServiceRequest,
    ServiceRegistration,
)


def _require_wallet_access(auth: AuthContext, wallet_id: str) -> None:
    auth.require_wallet_access(wallet_id)


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
    initial = (
        Decimal(str(request.initial_credits))
        if request.initial_credits
        else Decimal("0")
    )
    return await money.create_sponsor_wallet(
        sponsor_name=request.sponsor_name,
        email=request.email,
        initial_credits=initial,
        currency=request.currency,
        metadata=request.metadata,
        owner_key=api_key,
        require_kyc=request.require_kyc,
    )


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
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, request.sponsor_wallet_id)
    try:
        return await money.create_agent_wallet(
            sponsor_wallet_id=request.sponsor_wallet_id,
            agent_id=request.agent_id,
            budget_credits=Decimal(str(request.budget_credits)),
            daily_limit=(
                Decimal(str(request.daily_limit))
                if request.daily_limit
                else None
            ),
            auto_refill=request.auto_refill,
            auto_refill_threshold=Decimal(str(request.auto_refill_threshold)),
            auto_refill_amount=Decimal(str(request.auto_refill_amount)),
            owner_key=auth.raw_key,
        )
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "insufficient_funds",
                "message": (
                    f"Insufficient funds in sponsor wallet: "
                    f"balance={e.current_balance}, required={e.required_amount}"
                ),
                "wallet_id": e.wallet_id,
                "current_balance": float(e.current_balance),
                "required_amount": float(e.required_amount),
                "shortfall": float(e.shortfall),
            },
        )
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
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, request.parent_wallet_id)
    try:
        response = await money.create_child_wallet(
            parent_wallet_id=request.parent_wallet_id,
            child_agent_id=request.child_agent_id,
            budget_credits=Decimal(str(request.budget_credits)),
            max_spend=Decimal(str(request.max_spend)),
            task_description=request.task_description,
            ttl_seconds=request.ttl_seconds,
            auto_reclaim=request.auto_reclaim,
            owner_key=auth.raw_key,
        )
        return ChildWalletResponse(
            wallet_id=response.wallet_id,
            wallet_type=response.wallet_type,
            parent_wallet_id=response.sponsor_wallet_id,
            child_agent_id=response.child_agent_id,
            balance=response.balance,
            max_spend=response.max_spend,
            spent=0.0,
            task_description=response.task_description or "",
            ttl_seconds=response.ttl_seconds,
            auto_reclaim=True,
            status=response.status,
            created_at=response.created_at,
        )
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "insufficient_funds",
                "wallet_id": e.wallet_id,
                "current_balance": str(e.current_balance),
                "required_amount": str(e.required_amount),
                "shortfall": str(e.shortfall),
            },
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
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, wallet_id)
    try:
        result = await money.reclaim_child_wallet(wallet_id)
        return ReclaimResponse(
            child_wallet_id=result["child_wallet_id"],
            parent_wallet_id=result["parent_wallet_id"],
            credits_reclaimed=result["credits_reclaimed"],
            parent_balance_after=result["parent_balance_after"],
            child_status=result["child_status"],
        )
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "reclaim_error", "message": str(e)},
        )


@router.get(
    "/wallets/{wallet_id}/swarm",
    response_model=SwarmBudgetSummary,
    summary="Get swarm budget summary",
    description="Hierarchical budget summary for an agent's child wallets.",
)
async def get_swarm_budget(
    wallet_id: str,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, wallet_id)
    try:
        result = await money.get_swarm_budget(wallet_id)
        return SwarmBudgetSummary(
            parent_wallet_id=result["parent_wallet_id"],
            parent_balance=result["parent_balance"],
            total_delegated=result["total_delegated"],
            total_reclaimed=result["total_reclaimed"],
            active_children=result["active_children"],
            completed_children=result["completed_children"],
            frozen_children=result["frozen_children"],
            children=result["children"],
        )
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/wallets/{wallet_id}",
    response_model=WalletResponse,
    summary="Get wallet details",
)
async def get_wallet(
    wallet_id: str,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, wallet_id)
    wallet = await money.get_wallet(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


@router.get(
    "/wallets",
    response_model=WalletListResponse,
    summary="List wallets",
)
async def list_wallets(
    wallet_type: str | None = Query(None, description="Filter by wallet type"),
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    if auth.is_bootstrap_admin:
        wallets = await money.list_wallets(wallet_type=wallet_type)
    else:
        wallet = await money.get_wallet(auth.wallet_id or "")
        wallets = [wallet] if wallet else []
        if wallet_type:
            wallets = [w for w in wallets if w.wallet_type.value == wallet_type]
    return WalletListResponse(wallets=wallets, total=len(wallets))


# --- Ledger ---

@router.get(
    "/ledger/{wallet_id}",
    response_model=LedgerResponse,
    summary="Get wallet ledger",
)
async def get_ledger(
    wallet_id: str,
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, wallet_id)
    entries = await money.get_ledger(wallet_id, limit)

    period_credits = sum(e.amount for e in entries if e.amount > 0)
    period_debits = sum(abs(e.amount) for e in entries if e.amount < 0)

    return LedgerResponse(
        entries=entries,
        total=len(entries),
        wallet_id=wallet_id,
        period_credits=period_credits,
        period_debits=period_debits,
    )


# --- Charging ---

@router.post(
    "/charge",
    summary="Charge a wallet for API usage",
)
async def charge_wallet(
    wallet_id: str,
    service_category: ServiceCategory | None = None,
    service: ServiceCategory | None = Query(
        None,
        description="Service category (alias for service_category)",
    ),
    units: float = Query(1.0, gt=0, description="Number of units consumed"),
    request_path: str | None = None,
    description: str | None = None,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, wallet_id)
    category = service_category or service
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "missing_service",
                "message": "service_category is required",
            },
        )
    try:
        result = await money.charge(
            wallet_id=wallet_id,
            service_category=category,
            units=Decimal(str(units)),
            request_path=request_path,
            description=description or "",
        )

        if isinstance(result, InsufficientFundsResponse):
            raise HTTPException(status_code=402, detail=result.model_dump())

        return result
    except WalletFrozenError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "wallet_frozen",
                "wallet_id": e.wallet_id,
                "reason": e.reason,
                "message": (
                    "Wallet has been frozen due to anomalous spend velocity. "
                    "Contact sponsor."
                ),
            },
        )


# --- Top-Up ---

@router.post(
    "/top-up",
    response_model=TopUpResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Top up a sponsor wallet",
)
async def top_up_wallet(
    request: TopUpRequest,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    _require_wallet_access(auth, request.wallet_id)
    try:
        return await money.top_up(
            wallet_id=request.wallet_id,
            amount_fiat=Decimal(str(request.amount_fiat)),
            payment_method=request.payment_method,
            payment_token=request.payment_token,
        )
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KYCVerificationRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "kyc_required",
                "wallet_id": e.wallet_id,
                "kyc_status": e.kyc_status,
                "message": str(e),
                "verification_url": f"/v1/kyc/sessions?wallet_id={e.wallet_id}",
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "topup_error", "message": str(e)},
        )


@router.post(
    "/top-up/prepare",
    summary="Prepare a fiat top-up via Stripe",
    description=(
        "Create a Stripe PaymentIntent for fiat payment. "
        "After payment succeeds, credits are minted automatically via webhook. "
        "Requires KYC verification if enabled for the wallet."
    ),
)
async def prepare_top_up(
    wallet_id: str,
    amount_fiat: float = Query(..., gt=0, description="Amount in fiat currency (USD)"),
    currency: str = Query("USD", description="Fiat currency code"),
    auth: AuthContext = Depends(get_auth_context),
):
    _require_wallet_access(auth, wallet_id)
    """
    Prepare a fiat top-up by creating a Stripe PaymentIntent.

    Flow:
    1. Client calls this endpoint to get a client_secret
    2. Client uses Stripe.js to complete payment in browser
    3. Stripe sends webhook to /v1/webhooks/stripe
    4. Webhook handler mints credits to the wallet

    Returns:
        {
            "client_secret": str,
            "payment_intent_id": str,
            "amount_credits": int,
            "amount_fiat": float,
            "currency": str,
        }
    """
    from ..core.config import get_settings
    settings = get_settings()

    if settings.KYC_REQUIRED_FOR_TOPUP:
        from ..services.kyc_service import get_kyc_service
        kyc_service = get_kyc_service()
        kyc_status = await kyc_service.get_verification_status(wallet_id)
        if kyc_status["kyc_status"] != "verified":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "kyc_required",
                    "wallet_id": wallet_id,
                    "kyc_status": kyc_status["kyc_status"],
                    "message": (
                        f"KYC verification required. "
                        f"Current status: {kyc_status['kyc_status']}"
                    ),
                    "verification_url": "/v1/kyc/sessions",
                },
            )

    stripe_integration = get_stripe_integration()

    try:
        result = await stripe_integration.create_top_up_intent(
            wallet_id=wallet_id,
            amount_fiat=Decimal(str(amount_fiat)),
            currency=currency,
        )
        return result
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "topup_prepare_error", "message": str(e)},
        )


@router.post(
    "/transfer",
    summary="Transfer credits between wallets",
    description="Transfer credits from one wallet to another (agent-to-agent handoff).",
)
async def transfer_wallets(
    from_wallet_id: str = Query(..., description="Source wallet ID"),
    to_wallet_id: str = Query(..., description="Destination wallet ID"),
    amount: float = Query(..., gt=0, description="Amount of credits to transfer"),
    description: str | None = Query(None, description="Optional transfer description"),
    correlation_id: str | None = Query(
        None,
        description="Optional ID to link related transfers",
    ),
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    """
    Transfer credits between two wallets.

    This enables agent-to-agent payments for completed tasks.
    Both wallets are locked during the transaction for ACID compliance.
    """
    _require_wallet_access(auth, from_wallet_id)
    try:
        result = await money.transfer(
            from_wallet_id=from_wallet_id,
            to_wallet_id=to_wallet_id,
            amount=Decimal(str(amount)),
            description=description or "",
            correlation_id=correlation_id,
        )
        return result
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_funds",
                "wallet_id": e.wallet_id,
                "shortfall": float(e.shortfall),
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "transfer_error", "message": str(e)},
        )


# --- Pricing ---

@router.get(
    "/pricing",
    response_model=PricingTableResponse,
    summary="Get pricing table",
)
async def get_pricing(
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    from datetime import datetime, timezone
    return PricingTableResponse(
        pricing=money.get_pricing_table(),
        exchange_rate=EXCHANGE_RATE,
        last_updated=datetime.now(timezone.utc),
    )


# --- Arbitrage ---

@router.get(
    "/arbitrage",
    response_model=ArbitrageReport,
    summary="Get arbitrage report",
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
)
async def get_alerts(
    wallet_id: str | None = Query(None),
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    if wallet_id:
        _require_wallet_access(auth, wallet_id)
        wallet_filter = wallet_id
    else:
        wallet_filter = None if auth.is_bootstrap_admin else auth.wallet_id
    alerts = await money.get_alerts(wallet_filter)
    unacknowledged = sum(1 for a in alerts if not a.acknowledged)
    return AlertListResponse(
        alerts=alerts,
        total=len(alerts),
        unacknowledged=unacknowledged,
    )


@router.post(
    "/services",
    response_model=ServiceRegistration,
    status_code=status.HTTP_201_CREATED,
    summary="Register a billable service",
    description=(
        "Register a new service in the marketplace that agents can discover "
        "and pay for."
    ),
)
async def register_service(
    request: RegisterServiceRequest,
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    """
    Register a billable service in the agent marketplace.

    The service will be discoverable by other agents via the services endpoint.
    Charges for this service will be credited to the owner's wallet.
    """
    try:
        registration = await money.register_service(
            owner_key=api_key,
            name=request.name,
            description=request.description,
            category=request.category,
            credits_per_unit=Decimal(str(request.credits_per_unit)),
            unit_name=request.unit_name,
            mcp_manifest=request.mcp_manifest,
        )
        return registration
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "service_registration_error", "message": str(e)},
        )


@router.get(
    "/services",
    summary="List available services",
    description="List all registered billable services in the marketplace.",
)
async def list_services(
    category: ServiceCategory | None = Query(None),
    active_only: bool = Query(True, description="Only return active services"),
    api_key: str = Depends(verify_api_key),
    money: AgentMoney = Depends(get_agent_money),
):
    """List all services, optionally filtered by category."""
    services = await money.list_services(category=category, active_only=active_only)
    return {"services": services, "total": len(services)}


@router.get(
    "/wallets/{wallet_id}/velocity",
    summary="Get spend velocity status",
    description="Get current spend velocity metrics for a wallet.",
)
async def get_velocity_status(
    wallet_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get current velocity status including hourly/daily spend vs limits."""
    from ..services.velocity_monitor import get_velocity_monitor

    _require_wallet_access(auth, wallet_id)
    monitor = get_velocity_monitor()
    return await monitor.get_velocity_status(wallet_id)


# --- Dry-Run Sandbox Endpoints ---

class CreateDryRunSessionRequest(BaseModel):
    """Start a dry-run session for simulating billing operations."""
    wallet_id: str = Field(..., description="Wallet to simulate charges against")


class DryRunSessionResponse(BaseModel):
    """Response when creating a dry-run session."""
    session_id: str
    wallet_id: str
    real_balance: float
    virtual_balance: float
    created_at: str
    expires_in_seconds: int = 900


class SimulatedChargeRequest(BaseModel):
    """Simulate a charge without affecting real balance."""
    wallet_id: str = Field(..., description="Wallet being simulated")
    service: ServiceCategory = Field(..., description="Service category to simulate")
    units: float = Field(default=1.0, description="Number of units")
    description: str | None = Field(None, description="Optional description")
    dry_run_session_id: str | None = Field(
        None,
        description="Session ID for session-based simulation",
    )


class SimulatedChargeResponse(BaseModel):
    """Result of a simulated charge."""
    dry_run: bool = True
    session_id: str
    wallet_id: str
    service_category: str
    units: float
    credits_would_charge: float
    simulated_balance_before: float
    simulated_balance_after: float
    would_succeed: bool
    reason: str | None = None


@router.post(
    "/dry-run/session",
    response_model=DryRunSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a dry-run session",
    description=(
        "Create a new dry-run session for simulating billing operations. "
        "All charges simulated within this session use a virtual balance "
        "derived from the wallet's real balance minus simulated charges. "
        "Sessions expire after 15 minutes.\n\n"
        "Use this to:\n"
        "- Test if a multi-step workflow fits within your budget\n"
        "- Estimate total cost before committing to execution\n"
        "- Plan complex agent workflows safely"
    ),
)
async def create_dry_run_session(
    request: CreateDryRunSessionRequest,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    """Start a new dry-run session for the specified wallet."""
    _require_wallet_access(auth, request.wallet_id)
    wallet = await money.get_wallet(request.wallet_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "wallet_not_found",
                "message": f"Wallet {request.wallet_id} not found",
            },
        )

    shadow_ledger = get_shadow_ledger()
    session = await shadow_ledger.create_session(
        wallet_id=request.wallet_id,
        real_balance=Decimal(str(wallet.balance)),
    )

    return DryRunSessionResponse(
        session_id=session.session_id,
        wallet_id=session.wallet_id,
        real_balance=float(session.real_balance),
        virtual_balance=float(session.virtual_balance),
        created_at=session.created_at.isoformat(),
        expires_in_seconds=900,
    )


@router.get(
    "/dry-run/session/{session_id}",
    summary="Get dry-run session status",
    description="Retrieve current state of a dry-run session.",
)
async def get_dry_run_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get the current state of a dry-run session."""
    shadow_ledger = get_shadow_ledger()
    session = await shadow_ledger.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "session_not_found",
                "message": f"Session {session_id} not found",
            },
        )

    _require_wallet_access(auth, session.wallet_id)
    return {
        "session_id": session.session_id,
        "wallet_id": session.wallet_id,
        "real_balance": float(session.real_balance),
        "virtual_balance": float(session.virtual_balance),
        "total_simulated": float(session.total_simulated),
        "charge_count": len(session.simulated_charges),
        "charges": [
            {
                "charge_id": c.charge_id,
                "service_category": c.service_category,
                "units": c.units,
                "credits": float(c.credits),
                "description": c.description,
            }
            for c in session.simulated_charges
        ],
        "created_at": session.created_at.isoformat(),
    }


@router.delete(
    "/dry-run/session/{session_id}",
    summary="End a dry-run session",
    description=(
        "End a dry-run session and get a summary of all simulated charges. "
        "This does NOT affect the real wallet - it's purely informational."
    ),
)
async def end_dry_run_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """End a dry-run session and return summary."""
    shadow_ledger = get_shadow_ledger()
    session = await shadow_ledger.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "session_not_found",
                "message": f"Session {session_id} not found",
            },
        )
    _require_wallet_access(auth, session.wallet_id)
    summary = await shadow_ledger.end_session(session_id)

    return {
        "session_id": summary.session_id,
        "wallet_id": summary.wallet_id,
        "created_at": summary.created_at.isoformat(),
        "ended_at": summary.ended_at.isoformat(),
        "total_simulated_credits": float(summary.total_simulated_credits),
        "charge_count": summary.charge_count,
        "real_balance": float(summary.real_balance),
        "virtual_balance_after": float(summary.virtual_balance_after),
        "charges": summary.simulated_charges,
    }


@router.post(
    "/dry-run/session/{session_id}/commit",
    summary="Commit sandbox session to billing",
    description=(
        "Commit all simulated charges to real billing. "
        "This applies all sandbox charges to the wallet's real balance. "
        "Use this after reviewing the simulation results and deciding to proceed."
    ),
)
async def commit_dry_run_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    """
    Commit a sandbox session to real billing.

    Applies all simulated charges to the real wallet.
    The session is ended after committing.
    """
    shadow_ledger = get_shadow_ledger()
    session = await shadow_ledger.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "session_not_found",
                "message": f"Session {session_id} not found",
            },
        )
    _require_wallet_access(auth, session.wallet_id)
    result = await shadow_ledger.commit_session(session_id, money)

    return {
        "session_id": result.session_id,
        "wallet_id": result.wallet_id,
        "committed_charges": result.committed_charges,
        "total_credits_deducted": float(result.total_credits_deducted),
        "real_balance_before": float(result.real_balance_before),
        "real_balance_after": float(result.real_balance_after),
        "ledger_entries": result.ledger_entries,
        "success": result.success,
        "message": result.message,
    }


@router.post(
    "/dry-run/session/{session_id}/revert",
    summary="Revert sandbox session",
    description=(
        "Revert a sandbox session and discard all simulated charges. "
        "No changes are made to the real wallet. "
        "This is useful when the simulation shows the operation would fail "
        "or you're not ready to proceed."
    ),
)
async def revert_dry_run_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Revert a sandbox session.

    Discards all simulated charges without affecting the real wallet.
    The session is ended after reverting.
    """
    shadow_ledger = get_shadow_ledger()
    session = await shadow_ledger.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "session_not_found",
                "message": f"Session {session_id} not found",
            },
        )
    _require_wallet_access(auth, session.wallet_id)
    result = await shadow_ledger.revert_session(session_id)

    return {
        "session_id": result.session_id,
        "wallet_id": result.wallet_id,
        "reverted": result.reverted,
        "message": result.message,
    }


@router.post(
    "/dry-run/charge",
    response_model=SimulatedChargeResponse,
    summary="Simulate a charge",
    description=(
        "Simulate a charge without affecting real balance or triggering "
        "velocity monitoring. "
        "Returns cost estimate and virtual balance impact.\n\n"
        "Options:\n"
        "- Use session_id for multi-step simulation (tracks cumulative cost)\n"
        "- Omit session_id for single-shot estimation"
    ),
)
async def simulate_charge(
    request: SimulatedChargeRequest,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
):
    """Simulate a charge operation."""
    session_id = request.dry_run_session_id

    if session_id:
        shadow_ledger = get_shadow_ledger()
        session = await shadow_ledger.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "session_not_found",
                    "message": f"Session {session_id} not found",
                },
            )
        _require_wallet_access(auth, session.wallet_id)
        result = await shadow_ledger.simulate_charge(
            session_id=session_id,
            service_category=request.service,
            units=request.units,
            description=request.description or "",
        )
        return SimulatedChargeResponse(
            dry_run=True,
            session_id=result.session_id,
            wallet_id=result.wallet_id,
            service_category=result.service_category,
            units=result.units,
            credits_would_charge=float(result.credits_would_charge),
            simulated_balance_before=result.simulated_balance_before,
            simulated_balance_after=result.simulated_balance_after,
            would_succeed=result.would_succeed,
            reason=result.reason,
        )

    _require_wallet_access(auth, request.wallet_id)
    wallet = await money.get_wallet(request.wallet_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "wallet_not_found",
                "message": f"Wallet {request.wallet_id} not found",
            },
        )

    result = await money.charge(
        wallet_id=request.wallet_id,
        service_category=request.service,
        units=Decimal(str(request.units)),
        description=request.description or "",
        dry_run=True,
        dry_run_session_id=None,
    )

    if hasattr(result, "credits_would_charge"):
        return SimulatedChargeResponse(
            dry_run=True,
            session_id=getattr(result, "session_id", ""),
            wallet_id=getattr(result, "wallet_id", request.wallet_id),
            service_category=getattr(result, "service_category", request.service.value),
            units=getattr(result, "units", request.units),
            credits_would_charge=float(
                getattr(result, "credits_would_charge", Decimal("0"))
            ),
            simulated_balance_before=float(
                getattr(result, "simulated_balance_before", wallet.balance)
            ),
            simulated_balance_after=float(
                getattr(result, "simulated_balance_after", wallet.balance)
            ),
            would_succeed=getattr(result, "would_succeed", True),
            reason=getattr(result, "reason", None),
        )

    return SimulatedChargeResponse(
        dry_run=True,
        session_id="",
        wallet_id=request.wallet_id,
        service_category=request.service.value,
        units=request.units,
        credits_would_charge=float(wallet.balance),
        simulated_balance_before=float(wallet.balance),
        simulated_balance_after=float(wallet.balance),
        would_succeed=True,
    )
