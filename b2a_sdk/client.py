"""
B2A SDK - Agent-Native Middleware API Client
============================================

Async Python client for the Agent-Native Middleware API.
Provides wallet management, telemetry, and billing for agent swarms.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger("b2a_sdk")


class B2AClient:
    """
    Core async client for the Agent-Native Middleware API.

    Usage:
        b2a = B2AClient(api_key="agt-xyz123")
        await b2a.charge("wallet_123", "iot_bridge", units=10)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.agentnative.io",
        timeout: float = 10.0,
    ):
        """
        Initialize the B2A client.

        Args:
            api_key: API key for authentication (X-API-Key header)
            base_url: Base URL of the middleware API
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "User-Agent": "b2a-sdk/0.2.0",
            },
            timeout=timeout,
        )

    async def charge(
        self,
        wallet_id: str,
        service_category: str,
        units: float = 1.0,
        request_path: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Charge a wallet for API usage (micro-metering).

        Args:
            wallet_id: The wallet to charge
            service_category: Service category (e.g., "iot_bridge", "content_factory")
            units: Number of units consumed (default: 1.0)
            request_path: Optional API path for tracking
            description: Optional description of the charge

        Returns:
            Ledger entry with action, amount, balance_after

        Raises:
            InsufficientFundsError: If wallet has insufficient balance
        """
        params = {
            "wallet_id": wallet_id,
            "service": service_category,
            "units": units,
        }
        if request_path:
            params["request_path"] = request_path
        if description:
            params["description"] = description

        response = await self._client.post("/v1/billing/charge", params=params)

        if response.status_code == 402:
            data = response.json().get("detail", {})
            raise InsufficientFundsError(
                wallet_id=wallet_id,
                shortfall=data.get("shortfall", "unknown"),
                top_up_url=f"{self.base_url}/dashboard/top-up?wallet={wallet_id}",
            )

        response.raise_for_status()
        return response.json()

    async def telemetry(
        self,
        event_type: str,
        source: str,
        message: str,
        severity: str = "info",
        stack_trace: str | None = None,
        **metadata: Any,
    ) -> None:
        """
        Fire-and-forget telemetry ingestion.

        Telemetry failures are silently swallowed to prevent
        blocking agent execution.

        Args:
            event_type: Event type (error, warning, api_call, etc.)
            source: Originating service/module name
            message: Human-readable event message
            severity: Severity level (critical, high, medium, low, info)
            stack_trace: Optional stack trace for errors
            **metadata: Additional structured context
        """
        payload = {
            "event_type": event_type,
            "source": source,
            "message": message,
            "severity": severity,
            "metadata": metadata,
        }
        if stack_trace:
            payload["stack_trace"] = stack_trace

        try:
            response = await self._client.post(
                "/v1/telemetry/events/single",
                json=payload,
            )
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Telemetry push failed (non-blocking): {e}")

    async def create_sponsor_wallet(
        self,
        sponsor_name: str,
        email: str,
        initial_credits: float = 0.0,
    ) -> dict[str, Any]:
        """
        Create a sponsor (liability sink) wallet.

        Args:
            sponsor_name: Name of the human sponsor
            email: Sponsor's email address
            initial_credits: Starting credit balance

        Returns:
            Created wallet details including wallet_id
        """
        response = await self._client.post(
            "/v1/billing/wallets/sponsor",
            json={
                "sponsor_name": sponsor_name,
                "email": email,
                "initial_credits": initial_credits,
            },
        )
        response.raise_for_status()
        return response.json()

    async def create_agent_wallet(
        self,
        sponsor_wallet_id: str,
        agent_id: str,
        budget_credits: float,
        daily_limit: float | None = None,
    ) -> dict[str, Any]:
        """
        Provision an agent wallet from a sponsor's balance.

        Args:
            sponsor_wallet_id: ID of the sponsoring wallet
            agent_id: Unique identifier for the agent
            budget_credits: Credits to provision
            daily_limit: Optional daily spending limit

        Returns:
            Created agent wallet details
        """
        payload = {
            "sponsor_wallet_id": sponsor_wallet_id,
            "agent_id": agent_id,
            "budget_credits": budget_credits,
        }
        if daily_limit:
            payload["daily_limit"] = daily_limit

        response = await self._client.post(
            "/v1/billing/wallets/agent",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_wallet(self, wallet_id: str) -> dict[str, Any]:
        """Get wallet details by ID."""
        response = await self._client.get(f"/v1/billing/wallets/{wallet_id}")
        response.raise_for_status()
        return response.json()

    async def list_wallets(
        self,
        wallet_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all wallets, optionally filtered by type."""
        params = {}
        if wallet_type:
            params["wallet_type"] = wallet_type

        response = await self._client.get("/v1/billing/wallets", params=params)
        response.raise_for_status()
        return response.json()["wallets"]

    async def get_balance(self, wallet_id: str) -> float:
        """Get the current balance of a wallet."""
        wallet = await self.get_wallet(wallet_id)
        return wallet["balance"]

    async def get_pricing(self) -> dict[str, Any]:
        """Get the current pricing table."""
        response = await self._client.get("/v1/billing/pricing")
        response.raise_for_status()
        return response.json()

    async def prepare_top_up(
        self,
        wallet_id: str,
        amount_fiat: float,
        currency: str = "USD",
    ) -> dict[str, Any]:
        """
        Prepare a fiat top-up via Stripe.

        Returns a client_secret for Stripe Elements.

        Args:
            wallet_id: Wallet to credit
            amount_fiat: Amount in fiat currency
            currency: Currency code (default: USD)

        Returns:
            Stripe PaymentIntent details including client_secret
        """
        response = await self._client.post(
            "/v1/billing/top-up/prepare",
            params={
                "wallet_id": wallet_id,
                "amount_fiat": amount_fiat,
                "currency": currency,
            },
        )
        response.raise_for_status()
        return response.json()

    async def health_check(self) -> dict[str, Any]:
        """Check API health status."""
        response = await self._client.get("/health")
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "B2AClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


class InsufficientFundsError(Exception):
    """
    Raised when a wallet has insufficient funds for a charge.

    Attributes:
        wallet_id: The wallet that ran out of funds
        shortfall: How many more credits were needed
        top_up_url: URL to top up the wallet
    """

    def __init__(
        self,
        wallet_id: str,
        shortfall: float | str,
        top_up_url: str,
    ):
        self.wallet_id = wallet_id
        self.shortfall = float(shortfall) if shortfall != "unknown" else None
        self.top_up_url = top_up_url
        super().__init__(
            f"Insufficient funds in wallet {wallet_id}. "
            f"Shortfall: {self.shortfall} credits. "
            f"Top up at: {top_up_url}"
        )
