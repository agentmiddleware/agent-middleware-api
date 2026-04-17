"""Internal tool implementations."""

from typing import Any, Callable
from langchain_core.tools import StructuredTool, tool

from .client import B2AClient


def create_mcp_tool(client: B2AClient) -> StructuredTool:
    """Create a LangChain tool that calls MCP endpoints."""

    async def call_mcp(tool_name: str, arguments: dict[str, Any] = None) -> str:
        """Call an MCP tool on the Agent Middleware API.

        Args:
            tool_name: Name of the MCP tool to call
            arguments: Arguments to pass to the tool
        """
        if arguments is None:
            arguments = {}
        result = await client.call_mcp_tool(tool_name, arguments)
        return str(result)

    return StructuredTool.from_function(
        func=call_mcp,
        name="mcp_tool_call",
        description="Call a Model Context Protocol (MCP) tool from Agent Middleware API. "
        "Use this to access billable services like data indexing, content generation, etc.",
        args_schema={
            "tool_name": str,
            "arguments": dict,
        },
    )


def create_awi_tool(client: B2AClient) -> StructuredTool:
    """Create a LangChain tool for AWI web interactions."""

    async def execute_web_action(
        action: str,
        target_url: str = None,
        session_id: str = None,
        parameters: dict[str, Any] = None,
    ) -> str:
        """Execute an Agentic Web Interface (AWI) action.

        Args:
            action: AWI action name (e.g., 'search_and_sort', 'add_to_cart')
            target_url: URL to interact with (creates new session)
            session_id: Existing session ID to continue
            parameters: Action-specific parameters
        """
        if parameters is None:
            parameters = {}

        if not session_id:
            if not target_url:
                return "Error: Either session_id or target_url required"
            session = await client.create_awi_session(target_url)
            session_id = session.get("session_id")

        result = await client.execute_awi_action(session_id, action, parameters)
        return str(result)

    return StructuredTool.from_function(
        func=execute_web_action,
        name="awi_web_action",
        description="Execute Agentic Web Interface (AWI) actions on websites. "
        "Enables agents to interact with web interfaces using semantic actions.",
        args_schema={
            "action": str,
            "target_url": str,
            "session_id": str,
            "parameters": dict,
        },
    )


def create_wallet_tool(client: B2AClient) -> StructuredTool:
    """Create a LangChain tool for wallet operations."""

    async def get_balance() -> str:
        """Get current wallet balance."""
        balance = await client.get_balance()
        return f"Balance: {balance} credits"

    return StructuredTool.from_function(
        func=get_balance,
        name="wallet_balance",
        description="Get the current wallet balance from Agent Middleware API.",
    )


def create_langgraph_tools(client: B2AClient) -> list[Callable]:
    """Get tools formatted for LangGraph ReAct agents."""
    return [
        create_mcp_tool(client),
        create_awi_tool(client),
        create_wallet_tool(client),
    ]
