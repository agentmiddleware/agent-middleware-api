"""
MCP Server Generator
====================

Generates MCP-compliant manifests and standalone Python servers from
registered services.

Supports two modes:
1. Dynamic MCP Proxy: Live server mounted on FastAPI (zero infra for users)
2. Standalone Script: Generated Python file using the official MCP SDK

MCP Protocol Reference: https://modelcontextprotocol.io/
"""

import logging
from datetime import datetime, timezone
from typing import Any

from ..services.service_registry import ServiceRegistry, get_service_registry
from ..schemas.billing import ServiceCategory

logger = logging.getLogger(__name__)

MCP_TOOLS_JSON_VERSION = "1.0"
MCP_SERVER_VERSION = "1.0"


class McpGenerator:
    """
    Generates MCP-compliant manifests and standalone servers.

    MCP Manifest Structure (tools.json):
    {
        "version": "1.0",
        "name": "B2A Service Marketplace",
        "description": "...",
        "tools": [
            {
                "name": "service_name",
                "description": "...",
                "inputSchema": { ... },
                "annotations": {
                    "creditsPerCall": 10.0,
                    "unitName": "call",
                    "category": "content_factory"
                }
            }
        ]
    }
    """

    def __init__(self, registry: ServiceRegistry | None = None):
        self.registry = registry or get_service_registry()

    def generate_tools_json(
        self,
        category: ServiceCategory | None = None,
        include_local: bool = True,
        include_persistent: bool = True,
    ) -> dict[str, Any]:
        """
        Generate a tools.json manifest for MCP discovery.

        This is the standard MCP server manifest format.
        Agents can fetch this to discover available tools.
        """
        services = []

        if include_local:
            local_services = self.registry._local_registry
            for service in local_services.values():
                if category and service.get("category") != category.value:
                    continue
                services.append(self._service_to_mcp_tool(service))

        if include_persistent:
            import asyncio
            persistent_services = asyncio.get_event_loop().run_until_complete(
                self.registry.list_persistent(category=category)
            )
            for service in persistent_services:
                services.append(self._service_to_mcp_tool(service))

        return {
            "version": MCP_TOOLS_JSON_VERSION,
            "name": "B2A Service Marketplace",
            "description": "Billable AI agent services powered by the B2A economy. "
                "Each tool invocation deducts credits from the caller's wallet.",
            "tools": services,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def generate_tools_json_async(
        self,
        category: ServiceCategory | None = None,
        include_local: bool = True,
        include_persistent: bool = True,
    ) -> dict[str, Any]:
        """Async version of generate_tools_json."""
        services = []

        if include_local:
            local_services = self.registry._local_registry
            for service in local_services.values():
                if category and service.get("category") != category.value:
                    continue
                services.append(self._service_to_mcp_tool(service))

        if include_persistent:
            persistent_services = await self.registry.list_persistent(category=category)
            for service in persistent_services:
                services.append(self._service_to_mcp_tool(service))

        return {
            "version": MCP_TOOLS_JSON_VERSION,
            "name": "B2A Service Marketplace",
            "description": "Billable AI agent services powered by the B2A economy. "
                "Each tool invocation deducts credits from the caller's wallet.",
            "tools": services,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _service_to_mcp_tool(self, service: dict) -> dict[str, Any]:
        """Convert a service record to MCP tool format."""
        tool = {
            "name": service["service_id"],
            "description": service.get("description", ""),
            "inputSchema": service.get(
                "input_schema", {"type": "object", "properties": {}}
            ),
        }

        annotations = {
            "creditsPerCall": service.get("credits_per_unit", 1.0),
            "unitName": service.get("unit_name", "call"),
            "category": service.get("category", "unknown"),
        }

        if service.get("owner_wallet_id"):
            annotations["providerWallet"] = service["owner_wallet_id"]

        if service.get("output_schema"):
            annotations["hasOutputSchema"] = True

        tool["annotations"] = annotations

        return tool

    def generate_standalone_server(
        self,
        output_path: str,
        title: str = "B2A Custom MCP Server",
        description: str = "Custom MCP server generated from B2A marketplace",
        transport: str = "stdio",
    ) -> str:
        """
        Generate a standalone MCP server Python script.

        This script uses the official MCP Python SDK and can be run
        locally or embedded in other applications.

        Args:
            output_path: Where to write the generated script
            title: Server title
            description: Server description
            transport: "stdio" (default) or "sse"

        Returns:
            Path to the generated script
        """
        services = list(self.registry._local_registry.values())

        tools_code = []
        for service in services:
            name = service["service_id"]
            input_schema = service.get("input_schema", {})
            input_props = input_schema.get("properties", {})
            required = input_schema.get("required", [])

            params_code = []
            for prop_name, prop_def in input_props.items():
                prop_type = prop_def.get("type", "string")
                is_required = prop_name in required
                default = "" if is_required else " = None"
                params_code.append(f"    {prop_name}: {prop_type}{default}")

            if not params_code:
                params_code = ["    input_data: dict = {}"]

            tools_code.append(f'''
@mcp.tool()
async def {name.replace("-", "_")}({",".join([""] + params_code)}) -> dict:
    """
    {service.get("description", "B2A service: " + name)}
    
    Cost: {service.get("credits_per_unit", 1.0)} credits per
    {service.get("unit_name", "call")}
    Category: {service.get("category", "unknown")}
    """
    return await call_b2a_service(
        service_id="{name}",
        input_data={{"input_data": input_data}},
        wallet_id=os.getenv("B2A_WALLET_ID"),
        api_key=os.getenv("B2A_API_KEY"),
        api_url=os.getenv("B2A_API_URL", "http://localhost:8000"),
    )
''')

        script = f'''#!/usr/bin/env python3
"""
{title}
=============

Generated MCP Server using B2A SDK
Generated at: {datetime.now(timezone.utc).isoformat()}

Usage:
    # Set environment variables
    export B2A_API_KEY=your-api-key
    export B2A_WALLET_ID=your-wallet-id
    export B2A_API_URL=https://api.b2a.dev  # optional

    # Run the server
    python {output_path.split("/")[-1]}
    
    # Or with SSE transport (requires uvicorn)
    python {output_path.split("/")[-1]} --transport sse --port 8001
"""

import os
import json
import asyncio
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp")
    raise

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx")
    raise


mcp = FastMCP("{title}")


async def call_b2a_service(
    service_id: str,
    input_data: dict,
    wallet_id: str | None,
    api_key: str | None,
    api_url: str = "http://localhost:8000",
) -> dict:
    """
    Call a B2A service through the billing gateway.
    
    This function handles:
    - Authentication (X-API-Key header)
    - Wallet context (mcp_context field)
    - Credit deduction
    - Velocity monitoring
    """
    if not wallet_id:
        raise ValueError("B2A_WALLET_ID environment variable not set")
    if not api_key:
        raise ValueError("B2A_API_KEY environment variable not set")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{{api_url}}/v1/billing/services/{{service_id}}/invoke",
            headers={{
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            }},
            json={{
                "caller_wallet_id": wallet_id,
                "input_data": input_data,
            }},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


{"".join(tools_code)}


if __name__ == "__main__":
    import sys

    transport = "stdio"
    port = 8001

    if len(sys.argv) > 1:
        if sys.argv[1] == "--transport" and len(sys.argv) > 2:
            transport = sys.argv[2]
        if sys.argv[1] == "--port" and len(sys.argv) > 2:
            port = int(sys.argv[3])

    if transport == "sse":
        mcp.run(transport="sse", port=port)
    else:
        mcp.run()
'''

        with open(output_path, "w") as f:
            f.write(script)

        logger.info(f"Generated standalone MCP server: {output_path}")
        return output_path

    def generate_tools_list_response(
        self,
        category: ServiceCategory | None = None,
    ) -> dict[str, Any]:
        """
        Generate a tools/list MCP protocol response.

        This is the JSON-RPC response format for the MCP protocol's
        tools/list method.
        """
        manifest = self.generate_tools_json(category=category)
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": manifest["tools"],
            },
        }


_mcp_generator: McpGenerator | None = None


def get_mcp_generator() -> McpGenerator:
    """Get or create the global McpGenerator singleton."""
    global _mcp_generator
    if _mcp_generator is None:
        _mcp_generator = McpGenerator()
    return _mcp_generator
