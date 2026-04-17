"""AutoGen function tools for Agent Middleware API."""

from typing import Any
from autogen.agentchat.conversable_agent import ConversableAgent
from autogen.core import FunctionCall

from .client import B2AClient


class B2AFunctionTool:
    """AutoGen-compatible function tool for Agent Middleware API.

    Provides MCP tools, AWI sessions, and wallet operations
    as callable functions for AutoGen agents.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str | None = None,
        wallet_id: str | None = None,
    ):
        self.client = B2AClient(
            api_url=api_url,
            api_key=api_key,
            wallet_id=wallet_id,
        )

    async def list_mcp_tools(self) -> list[dict[str, Any]]:
        """List all available MCP tools."""
        return await self.client.get_mcp_tools()

    async def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call an MCP tool by name."""
        if arguments is None:
            arguments = {}
        return await self.client.call_mcp_tool(tool_name, arguments)

    async def create_awi_session(
        self,
        target_url: str,
        max_steps: int = 100,
    ) -> dict[str, Any]:
        """Create an AWI session for web interaction."""
        return await self.client.create_awi_session(target_url, max_steps)

    async def get_wallet_balance(self) -> float:
        """Get current wallet balance."""
        return await self.client.get_balance()

    def get_function_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI function schemas for all available operations."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_mcp_tools",
                    "description": "List all available MCP tools from Agent Middleware API",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_mcp_tool",
                    "description": "Call a specific MCP tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool_name": {
                                "type": "string",
                                "description": "Name of the MCP tool to call",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Arguments to pass to the tool",
                            },
                        },
                        "required": ["tool_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_awi_session",
                    "description": "Create an Agentic Web Interface session for web interaction",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_url": {
                                "type": "string",
                                "description": "URL of the website to interact with",
                            },
                            "max_steps": {
                                "type": "integer",
                                "description": "Maximum steps for the session",
                                "default": 100,
                            },
                        },
                        "required": ["target_url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_wallet_balance",
                    "description": "Get the current wallet balance in credits",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]


def register_b2a_tools(agent: ConversableAgent, b2a_tool: B2AFunctionTool) -> None:
    """Register B2A tools with an AutoGen agent.

    Args:
        agent: AutoGen ConversableAgent instance
        b2a_tool: B2AFunctionTool instance configured with API credentials
    """
    function_schemas = b2a_tool.get_function_schemas()
    for schema in function_schemas:
        agent.register_function(
            function_map={
                schema["function"]["name"]: getattr(
                    b2a_tool, schema["function"]["name"]
                ),
            }
        )
