"""CrewAI Tool for Agent Middleware API."""

from typing import Any, Type
from crewai.tools import BaseTool
from pydantic import BaseModel

from .client import B2AClient


class MCPToolSchema(BaseModel):
    """Schema for MCP tool input."""

    tool_name: str
    arguments: dict[str, Any] = {}


class AWISessionSchema(BaseModel):
    """Schema for AWI session creation."""

    target_url: str
    max_steps: int = 100


class WalletBalanceSchema(BaseModel):
    """Schema for wallet balance check."""


class CrewAIB2ATool(BaseTool):
    """CrewAI tool for Agent Middleware API operations."""

    name: str = "Agent_Middleware_API"
    description: str = (
        "Access Agent Middleware API for MCP tools, AWI web interactions, and wallet operations. "
        "Use this to call billable services, interact with websites, and manage agent billing."
    )

    client: B2AClient | None = None
    api_url: str = "http://localhost:8000"
    api_key: str | None = None
    wallet_id: str | None = None

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str | None = None,
        wallet_id: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.api_url = api_url
        self.api_key = api_key
        self.wallet_id = wallet_id

    def _get_client(self) -> B2AClient:
        if self.client is None:
            self.client = B2AClient(
                api_url=self.api_url,
                api_key=self.api_key,
                wallet_id=self.wallet_id,
            )
        return self.client

    def _run(
        self,
        operation: str,
        **kwargs,
    ) -> str:
        """Synchronous operation (for CrewAI compatibility).

        Args:
            operation: One of 'list_tools', 'call_tool', 'create_session', 'balance'
            **kwargs: Operation-specific arguments
        """
        import asyncio

        client = self._get_client()

        try:
            if operation == "list_tools":
                tools = asyncio.get_event_loop().run_until_complete(
                    client.get_mcp_tools()
                )
                return str(tools)

            elif operation == "call_tool":
                tool_name = kwargs.get("tool_name")
                arguments = kwargs.get("arguments", {})
                result = asyncio.get_event_loop().run_until_complete(
                    client.call_mcp_tool(tool_name, arguments)
                )
                return str(result)

            elif operation == "create_session":
                target_url = kwargs.get("target_url")
                max_steps = kwargs.get("max_steps", 100)
                result = asyncio.get_event_loop().run_until_complete(
                    client.create_awi_session(target_url, max_steps)
                )
                return str(result)

            elif operation == "balance":
                balance = asyncio.get_event_loop().run_until_complete(
                    client.get_balance()
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
            if operation == "list_tools":
                tools = await client.get_mcp_tools()
                return str(tools)

            elif operation == "call_tool":
                tool_name = kwargs.get("tool_name")
                arguments = kwargs.get("arguments", {})
                result = await client.call_mcp_tool(tool_name, arguments)
                return str(result)

            elif operation == "create_session":
                target_url = kwargs.get("target_url")
                max_steps = kwargs.get("max_steps", 100)
                result = await client.create_awi_session(target_url, max_steps)
                return str(result)

            elif operation == "balance":
                balance = await client.get_balance()
                return f"Balance: {balance} credits"

            else:
                return f"Unknown operation: {operation}"

        except Exception as e:
            return f"Error: {str(e)}"
