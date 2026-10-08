"""CrewAI Tool for Agent Middleware API."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from crewai.tools import BaseTool
from pydantic import BaseModel, PrivateAttr

from b2a_sdk.errors import PermitDeniedError
from b2a_sdk.models import PermitRequest
from b2a_sdk.permit_cache import PermitCache, is_permit_lifecycle_denial

from .client import B2AClient


class MCPToolSchema(BaseModel):
    """Schema for MCP tool input."""

    tool_name: str
    idempotency_key: str
    permit_idempotency_key: str
    arguments: dict[str, Any] = {}


class WalletBalanceSchema(BaseModel):
    """Schema for wallet balance check."""


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
    # Cache permits to avoid 409 on replay (server hashes full permit body including expires_at).
    # Entries expire with the permit itself and the cache holds at most a
    # small LRU-capped number of keys. permit_idempotency_key → permit_id.
    _permit_cache: PermitCache = PrivateAttr(default_factory=PermitCache)

    def __init__(
        self,
        api_key: str,
        wallet_id: str,
        base_url: str = "https://api.thisisatest.tech",
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

    def _get_client(self) -> B2AClient:
        if self.client is None:
            self.client = B2AClient(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self.client

    def _permit_request(self, tool_name: str, permit_key: str) -> PermitRequest:
        # Both sync and async entry points retain the body before sending it.
        # A lost response therefore cannot change the expiry on retry. A
        # retained body read past its own expiry is treated as a miss, so an
        # expired permit is resolved again instead of being reused.
        request = self._permit_cache.get_request(permit_key)
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
            self._permit_cache.store_request(permit_key, request)
        elif (
            request.subject_wallet_id != self.wallet_id
            or request.max_credits != self.permit_budget
            or request.allowed_tools != [tool_name]
        ):
            raise ValueError(
                "permit_idempotency_key reused with different permit terms"
            )
        return request

    async def _ensure_permit_id(self, tool_name: str, permit_key: str) -> str:
        """Resolve the cached permit id, creating the permit on a miss."""
        request = self._permit_request(tool_name, permit_key)
        permit_id = self._permit_cache.get_permit_id(permit_key)
        if permit_id is None:
            permit = await self._get_client().create_permit(
                request, idempotency_key=permit_key
            )
            self._permit_cache.store_permit(permit_key, permit)
            permit_id = permit.permit_id
        return permit_id

    def _note_invoke_denial(self, exc: PermitDeniedError, permit_key: str) -> None:
        # The permit is revoked or expired: drop the cached id so the next
        # attempt resolves again. The retained request body is kept, so the
        # retry replays the identical body under the same key and gets the
        # same denial instead of a fresh conflict.
        if is_permit_lifecycle_denial(exc):
            self._permit_cache.drop_permit(permit_key)

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
        import asyncio

        client = self._get_client()

        try:
            if operation == "discover_tools":
                tools = asyncio.get_event_loop().run_until_complete(
                    client.discover_tools()
                )
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

                permit_id = asyncio.get_event_loop().run_until_complete(
                    self._ensure_permit_id(tool_name, permit_idempotency_key)
                )

                try:
                    result = asyncio.get_event_loop().run_until_complete(
                        client.invoke_tool(
                            tool_name,
                            arguments,
                            wallet_id=self.wallet_id,
                            permit_id=permit_id,
                            idempotency_key=idempotency_key,
                        )
                    )
                except PermitDeniedError as exc:
                    self._note_invoke_denial(exc, permit_idempotency_key)
                    raise

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
                balance = asyncio.get_event_loop().run_until_complete(
                    client.get_balance(self.wallet_id)
                )
                return f"Balance: {balance} credits"

            else:
                return f"Unknown operation: {operation}"

        except Exception as e:
            return f"Error: {str(e)}"

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

                permit_id = await self._ensure_permit_id(
                    tool_name, permit_idempotency_key
                )

                try:
                    result = await client.invoke_tool(
                        tool_name,
                        arguments,
                        wallet_id=self.wallet_id,
                        permit_id=permit_id,
                        idempotency_key=idempotency_key,
                    )
                except PermitDeniedError as exc:
                    self._note_invoke_denial(exc, permit_idempotency_key)
                    raise

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
