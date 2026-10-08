"""Internal tool implementations."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from b2a_sdk.errors import PermitDeniedError
from b2a_sdk.models import PermitRequest
from b2a_sdk.permit_cache import PermitCache, is_permit_lifecycle_denial
from langchain_core.tools import StructuredTool

from .client import B2AClient


def create_mcp_tool(
    client: B2AClient,
    *,
    wallet_id: str,
    permit_budget: Decimal = Decimal(100),
    permit_ttl_minutes: int = 30,
) -> StructuredTool:
    """Create a LangChain tool that calls MCP endpoints via governed permit→invoke→receipt flow.

    Args:
        client: AgentMiddlewareClient instance
        wallet_id: Wallet ID for billing
        permit_budget: Maximum credits per permit (default 100)
        permit_ttl_minutes: Permit lifetime in minutes (default 30)
    """
    # Cache permits by permit_idempotency_key to avoid 409 on replay
    # Server hashes the FULL permit request body including expires_at.
    # Sending different expires_at with same key → 409 IdempotencyConflictError.
    # Keep the original body before sending and the ID after acknowledgement.
    # Entries expire with the permit itself and the cache holds at most a
    # small LRU-capped number of keys.
    permit_cache = PermitCache()

    async def call_mcp(
        tool_name: str,
        idempotency_key: str,
        permit_idempotency_key: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Call an MCP tool via permit→invoke→receipt flow.

        Args:
            tool_name: Name of the MCP tool to call
            idempotency_key: Caller-supplied idempotency key for invoke_tool (required)
            permit_idempotency_key: Caller-supplied permit idempotency key (required).
                Reused across replays to avoid creating multiple permits.
            arguments: Arguments to pass to the tool

        Idempotency and replay:
            On first call, creates a permit and caches permit_id by permit_idempotency_key.
            On replay with same permit_idempotency_key, reuses the cached permit_id.
            This avoids 409 IdempotencyConflictError from different expires_at timestamps.
        """
        if arguments is None:
            arguments = {}
        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key is required and must not be blank")
        if not permit_idempotency_key or not permit_idempotency_key.strip():
            raise ValueError("permit_idempotency_key is required and must not be blank")

        # Snapshot before awaiting creation, including a response lost after
        # acceptance. Concurrent coroutines also see this same request body. A
        # retained body read past its own expiry is treated as a miss, so an
        # expired permit is resolved again instead of being reused.
        request = permit_cache.get_request(permit_idempotency_key)
        if request is None:
            request = PermitRequest(
                issuer_wallet_id=wallet_id,
                subject_wallet_id=wallet_id,
                max_credits=permit_budget,
                expires_at=datetime.now(UTC) + timedelta(minutes=permit_ttl_minutes),
                allowed_tools=[tool_name],
                scopes=[f"tool:{tool_name}:invoke", "billing:charge"],
            )
            permit_cache.store_request(permit_idempotency_key, request)
        elif request.allowed_tools != [tool_name]:
            raise ValueError("permit_idempotency_key reused with different permit terms")

        permit_id = permit_cache.get_permit_id(permit_idempotency_key)
        if permit_id is None:
            permit = await client.create_permit(request, idempotency_key=permit_idempotency_key)
            permit_cache.store_permit(permit_idempotency_key, permit)
            permit_id = permit.permit_id

        try:
            result = await client.invoke_tool(
                tool_name,
                arguments,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key=idempotency_key,
            )
        except PermitDeniedError as exc:
            if is_permit_lifecycle_denial(exc):
                # The permit is revoked or expired: drop the cached id so the
                # next attempt resolves again. The retained request body is
                # kept, so the retry replays the identical body under the same
                # key and gets the same denial instead of a fresh conflict.
                permit_cache.drop_permit(permit_idempotency_key)
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

    # call_mcp is async, so it must go in the coroutine slot; passing it as
    # func makes ainvoke return an un-awaited coroutine object instead of a result.
    # The argument schema is inferred from call_mcp's signature: an explicit
    # args_schema dict must be JSON Schema, and a dict of Python types breaks
    # tool.args and LLM tool binding.
    return StructuredTool.from_function(
        coroutine=call_mcp,
        name="mcp_tool_call",
        description="Call a Model Context Protocol (MCP) tool from Agent Middleware API. "
        "Use this to access billable services like data indexing, content generation, etc. "
        "Returns signed receipts for all invocations. "
        "Requires both idempotency_key and permit_idempotency_key for safe replay.",
    )


def create_wallet_tool(client: B2AClient, *, wallet_id: str) -> StructuredTool:
    """Create a LangChain tool for wallet operations."""

    async def get_balance() -> str:
        """Get current wallet balance."""
        balance = await client.get_balance(wallet_id)
        return f"Balance: {balance} credits"

    return StructuredTool.from_function(
        coroutine=get_balance,
        name="wallet_balance",
        description="Get the current wallet balance from Agent Middleware API.",
    )


def create_langgraph_tools(
    client: B2AClient,
    *,
    wallet_id: str,
    permit_budget: Decimal = Decimal(100),
    permit_ttl_minutes: int = 30,
) -> list[Callable]:
    """Get tools formatted for LangGraph ReAct agents."""
    return [
        create_mcp_tool(
            client,
            wallet_id=wallet_id,
            permit_budget=permit_budget,
            permit_ttl_minutes=permit_ttl_minutes,
        ),
        create_wallet_tool(client, wallet_id=wallet_id),
    ]
