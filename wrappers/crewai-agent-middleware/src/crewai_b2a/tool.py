"""CrewAI Tool for Agent Middleware API."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
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


class B2AOperationSchema(BaseModel):
    """Arguments accepted by CrewAIB2ATool.

    CrewAI validates ``run()`` kwargs against ``args_schema`` and drops anything the
    schema does not declare. Without this schema CrewAI derives one from ``_run``'s
    signature, which keeps only ``operation`` and silently discards the governed keys.
    """

    operation: str = Field(
        description="One of 'discover_tools', 'call_tool', 'balance'"
    )
    tool_name: str | None = Field(
        default=None, description="call_tool: MCP tool to invoke"
    )
    idempotency_key: str | None = Field(
        default=None,
        description="call_tool: caller-supplied key, unique per invocation (required)",
    )
    permit_idempotency_key: str | None = Field(
        default=None,
        description="call_tool: caller-supplied permit key, stable across replays (required)",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="call_tool: arguments for the MCP tool"
    )


class CrewAIB2ATool(BaseTool):
    """CrewAI tool for Agent Middleware API operations via governed permit→invoke→receipt flow."""

    name: str = "Agent_Middleware_API"
    description: str = (
        "Access Agent Middleware API for MCP tools and wallet operations. "
        "Use this to call billable services and manage agent billing. "
        "All invocations return signed receipts."
    )

    client: B2AClient | None = None
    base_url: str = "https://api.thisisatest.tech"
    api_key: str
    wallet_id: str
    permit_budget: Decimal = Decimal("100")
    permit_ttl_minutes: int = 30
    args_schema: type[BaseModel] = B2AOperationSchema
    # Cache permits to avoid 409 on replay (server hashes full permit body including expires_at)
    _permit_cache: dict[str, str] = {}  # permit_idempotency_key → permit_id

    def __init__(
        self,
        api_key: str,
        wallet_id: str,
        base_url: str = "https://api.thisisatest.tech",
        permit_budget: Decimal = Decimal("100"),
        permit_ttl_minutes: int = 30,
        **kwargs,
    ):
        # BaseTool is a Pydantic model: declared fields must go through the
        # constructor, or validation fails before any attribute assignment runs.
        super().__init__(
            api_key=api_key,
            wallet_id=wallet_id,
            base_url=base_url,
            permit_budget=permit_budget,
            permit_ttl_minutes=permit_ttl_minutes,
            **kwargs,
        )
        self._permit_cache = {}  # Instance-specific cache

    def _get_client(self) -> B2AClient:
        if self.client is None:
            self.client = B2AClient(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self.client

    async def _run(
        self,
        operation: str,
        **kwargs,
    ) -> str:
        """Entry point for CrewAI's sync and async dispatchers.

        Declared ``async`` on purpose. ``BaseTool.run()`` and
        ``CrewStructuredTool.invoke()`` run a coroutine to completion with
        ``asyncio.run``, and ``CrewStructuredTool.ainvoke()`` awaits ``_run`` only
        when it is a coroutine function (a sync ``_run`` is pushed to a worker
        thread instead). The previous sync body bridged into
        ``asyncio.get_event_loop().run_until_complete``, which raises "There is no
        current event loop" after any earlier ``asyncio.run`` in the process.

        Args:
            operation: One of 'discover_tools', 'call_tool', 'balance'
            **kwargs: Operation-specific arguments
        """
        return await self._arun(operation, **kwargs)

    async def _arun(
        self,
        operation: str,
        **kwargs,
    ) -> str:
        """Asynchronous operation (preferred)."""
        client = self._get_client()

        try:
            if operation == "discover_tools":
                tools = await client.discover_tools()
                return str(
                    [{"name": t.name, "description": t.description} for t in tools]
                )

            elif operation == "call_tool":
                tool_name = kwargs.get("tool_name")
                idempotency_key = kwargs.get("idempotency_key")
                permit_idempotency_key = kwargs.get("permit_idempotency_key")
                arguments = kwargs.get("arguments", {})

                if not idempotency_key or not idempotency_key.strip():
                    return "Error: idempotency_key is required and must not be blank"

                if not permit_idempotency_key or not permit_idempotency_key.strip():
                    return "Error: permit_idempotency_key is required and must not be blank"

                # Check cache first - reuse existing permit to avoid 409 on replay
                if permit_idempotency_key in self._permit_cache:
                    permit_id = self._permit_cache[permit_idempotency_key]
                else:
                    request = PermitRequest(
                        issuer_wallet_id=self.wallet_id,
                        subject_wallet_id=self.wallet_id,
                        max_credits=self.permit_budget,
                        expires_at=datetime.now(timezone.utc)
                        + timedelta(minutes=self.permit_ttl_minutes),
                        allowed_tools=[tool_name],
                        scopes=[f"tool:{tool_name}:invoke", "billing:charge"],
                    )

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
                return f"Unknown operation: {operation}"

        except Exception as e:
            return f"Error: {str(e)}"
