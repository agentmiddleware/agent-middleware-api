"""CrewAI Tool for Agent Middleware API."""

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, TypeVar
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from b2a_sdk.models import PermitRequest

from .client import B2AClient


class MCPToolSchema(BaseModel):
    """Schema for MCP tool input."""

    tool_name: str
    idempotency_key: str
    permit_idempotency_key: str
    arguments: dict[str, Any] = {}


class WalletBalanceSchema(BaseModel):
    """Schema for wallet balance check."""


class CrewAIOperationSchema(BaseModel):
    """Input schema for the governed tool, wired as ``args_schema``.

    One tool serves three operations, so the schema carries the operation
    name plus the fields each operation needs. Wiring it lets CrewAI
    tool-calling parse and validate arguments instead of guessing from a
    free-text description.
    """

    operation: str = Field(
        description="One of 'discover_tools', 'call_tool', 'balance'."
    )
    tool_name: str | None = Field(
        default=None, description="MCP tool name (required for 'call_tool')."
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Caller-supplied idempotency key (required for 'call_tool').",
    )
    permit_idempotency_key: str | None = Field(
        default=None,
        description="Caller-supplied permit idempotency key (required for 'call_tool').",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments passed to the MCP tool."
    )


T = TypeVar("T")

# Local gateway default. A forgotten override must fail loudly with a
# connection error, never silently bill against a shared test host.
LOCAL_GATEWAY_URL = "http://127.0.0.1:8000"


def _await_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Drive a coroutine to completion from synchronous CrewAI entry points.

    Uses ``asyncio.run`` when no event loop is running. When called inside a
    running loop (where ``run_until_complete`` raises ``RuntimeError``), the
    coroutine runs to completion on a helper thread with its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class CrewAIB2ATool(BaseTool):
    """CrewAI tool for Agent Middleware API operations via governed permit→invoke→receipt flow."""

    name: str = "Agent_Middleware_API"
    description: str = (
        "Access Agent Middleware API for MCP tools and wallet operations. "
        "Use this to call billable services and manage agent billing. "
        "All invocations return signed receipts."
    )
    args_schema: type[BaseModel] = CrewAIOperationSchema

    client: B2AClient | None = None
    base_url: str = LOCAL_GATEWAY_URL
    api_key: str
    wallet_id: str
    permit_budget: Decimal = Decimal("100")
    permit_ttl_minutes: int = 30
    # Cache permits to avoid 409 on replay (server hashes full permit body including expires_at)
    _permit_cache: dict[str, str] = {}  # permit_idempotency_key → permit_id
    _permit_requests: dict[str, PermitRequest] = {}

    def __init__(
        self,
        api_key: str,
        wallet_id: str,
        base_url: str = LOCAL_GATEWAY_URL,
        permit_budget: Decimal = Decimal("100"),
        permit_ttl_minutes: int = 30,
        **kwargs,
    ):
        # BaseTool is a pydantic model: required fields must reach its
        # validator, so pass them through instead of assigning afterwards.
        super().__init__(
            api_key=api_key,
            wallet_id=wallet_id,
            base_url=base_url,
            permit_budget=permit_budget,
            permit_ttl_minutes=permit_ttl_minutes,
            **kwargs,
        )
        self._permit_cache = {}  # Instance-specific cache
        self._permit_requests = {}

    def _get_client(self) -> B2AClient:
        if self.client is None:
            self.client = B2AClient(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self.client

    def _permit_request(self, tool_name: str, permit_key: str) -> PermitRequest:
        # Both sync and async entry points retain the body before sending it.
        # A lost response therefore cannot change the expiry on retry.
        request = self._permit_requests.get(permit_key)
        if request is None:
            request = PermitRequest(
                issuer_wallet_id=self.wallet_id,
                subject_wallet_id=self.wallet_id,
                max_credits=self.permit_budget,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=self.permit_ttl_minutes),
                allowed_tools=[tool_name],
                scopes=[f"tool:{tool_name}:invoke", "billing:charge"],
            )
            self._permit_requests[permit_key] = request
        elif (
            request.subject_wallet_id != self.wallet_id
            or request.max_credits != self.permit_budget
            or request.allowed_tools != [tool_name]
        ):
            raise ValueError(
                "permit_idempotency_key reused with different permit terms"
            )
        return request

    def _run(
        self,
        operation: str,
        **kwargs,
    ) -> str:
        """Synchronous operation (for CrewAI compatibility).

        Args:
            operation: One of 'discover_tools', 'call_tool', 'balance'
            **kwargs: Operation-specific arguments
        """
        return _await_sync(self._arun(operation, **kwargs))

    async def _arun(
        self,
        operation: str,
        **kwargs,
    ) -> str:
        """Asynchronous operation (preferred).

        Raises the same typed errors as the LangChain wrapper: ValueError
        for missing or blank inputs, and the ``b2a_sdk`` error for gateway
        failures (auth, denial, idempotency conflict, short funds, uncertain
        delivery), so callers can tell a charge from a failure in code.
        """
        client = self._get_client()

        if operation == "discover_tools":
            tools = await client.discover_tools()
            return str([{"name": t.name, "description": t.description} for t in tools])

        elif operation == "call_tool":
            tool_name = kwargs.get("tool_name")
            idempotency_key = kwargs.get("idempotency_key")
            permit_idempotency_key = kwargs.get("permit_idempotency_key")
            arguments = kwargs.get("arguments", {})

            if not tool_name or not str(tool_name).strip():
                raise ValueError("tool_name is required and must not be blank")

            if not idempotency_key or not idempotency_key.strip():
                raise ValueError("idempotency_key is required and must not be blank")

            if not permit_idempotency_key or not permit_idempotency_key.strip():
                raise ValueError(
                    "permit_idempotency_key is required and must not be blank"
                )

            request = self._permit_request(tool_name, permit_idempotency_key)
            if permit_idempotency_key in self._permit_cache:
                permit_id = self._permit_cache[permit_idempotency_key]
            else:
                permit = await client.create_permit(
                    request, idempotency_key=permit_idempotency_key
                )
                permit_id = permit.permit_id
                self._permit_cache[permit_idempotency_key] = permit_id

            result = await client.invoke_tool(
                tool_name,
                arguments,
                wallet_id=self.wallet_id,
                permit_id=permit_id,
                idempotency_key=idempotency_key,
            )

            return str(
                {
                    "content": result.content,
                    "structured_content": result.structured_content,
                    "receipt_id": result.receipt.receipt_id,
                    "credits_charged": str(result.receipt.credits_charged),
                    "signature": result.receipt.signature,
                }
            )

        elif operation == "balance":
            balance = await client.get_balance(self.wallet_id)
            return f"Balance: {balance} credits"

        else:
            raise ValueError(
                f"Unknown operation: {operation!r}. "
                "Expected one of 'discover_tools', 'call_tool', 'balance'."
            )
