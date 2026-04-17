"""LangChain tools from Agent Middleware API."""

from typing import Any, Callable
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from .client import B2AClient


class MCPToolInput(BaseModel):
    """Input for MCP tool."""

    tool_name: str
    arguments: dict[str, Any]


def get_mcp_tools(client: B2AClient) -> list[BaseTool]:
    """Get LangChain tools from MCP registry.

    Args:
        client: B2AClient instance connected to Agent Middleware API

    Returns:
        List of LangChain BaseTool instances

    Example:
        client = B2AClient(api_key="...", wallet_id="...")
        tools = get_mcp_tools(client)
        for t in tools:
            result = await t.ainvoke({"tool_name": "my_tool", "arguments": {...}})
    """
    from ._tools import create_mcp_tool

    return create_mcp_tool(client)


def get_langgraph_tools(client: B2AClient) -> list[Callable]:
    """Get tools formatted for LangGraph.

    Args:
        client: B2AClient instance connected to Agent Middleware API

    Returns:
        List of callable tools compatible with LangGraph

    Example:
        from langgraph.prebuilt import create_react_agent
        client = B2AClient(api_key="...", wallet_id="...")
        tools = get_langgraph_tools(client)
        agent = create_react_agent(model, tools)
    """
    from ._tools import create_langgraph_tools

    return create_langgraph_tools(client)
