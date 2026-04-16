"""
MCP Router
==========

Dynamic MCP Proxy router for the B2A Service Marketplace.

Provides:
- /.well-known/mcp/tools.json - MCP manifest discovery
- /mcp/sse - Server-Sent Events transport
- /mcp/messages - JSON-RPC message handling

This enables agents to:
1. Discover available tools via tools.json
2. Execute tools with automatic billing + velocity monitoring
3. Receive results in real-time via SSE
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..services.service_registry import get_service_registry
from ..services.mcp_generator import get_mcp_generator
from ..schemas.billing import ServiceCategory
from .billing import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP"])


class McpContext(BaseModel):
    """MCP execution context passed in tool calls."""
    wallet_id: str = Field(..., description="Wallet to charge for this call")
    request_path: str | None = Field(None, description="Optional request path for tracking")


class ToolCallRequest(BaseModel):
    """MCP tool call request (tools/call method)."""
    name: str = Field(..., description="Tool name (service_id)")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    mcp_context: McpContext | None = Field(None, description="Billing context")


class ToolCallResponse(BaseModel):
    """MCP tool call response."""
    content: list[dict[str, Any]]
    isError: bool = False


@router.get("/tools.json", name="MCP Tools Manifest")
async def get_tools_json(
    category: ServiceCategory | None = None,
) -> JSONResponse:
    """
    Return the MCP tools.json manifest.

    This is the standard MCP server discovery endpoint.
    Agents should fetch this first to understand available tools.

    Query Parameters:
        category: Optional service category filter

    Returns:
        MCP tools.json manifest with tool definitions
    """
    generator = get_mcp_generator()
    manifest = await generator.generate_tools_json_async(category=category)
    return JSONResponse(content=manifest)


@router.get("/.well-known/mcp/tools.json")
async def well_known_tools_json() -> JSONResponse:
    """
    MCP tools manifest at the standard .well-known location.

    This follows the MCP specification for tool discovery.
    """
    generator = get_mcp_generator()
    manifest = await generator.generate_tools_json_async()
    return JSONResponse(content=manifest)


@router.post("/messages", name="MCP JSON-RPC Messages")
async def handle_messages(request: Request) -> JSONResponse:
    """
    Handle MCP JSON-RPC messages.

    Supports:
    - tools/list: List available tools
    - tools/call: Execute a tool

    The request body is a JSON-RPC 2.0 request.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    method = body.get("method")
    request_id = body.get("id")
    params = body.get("params", {})

    if method == "tools/list":
        result = await _handle_tools_list(params)
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        })

    elif method == "tools/call":
        try:
            result = await _handle_tools_call(params)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            })
        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                },
            })

    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        })


async def _handle_tools_list(params: dict) -> dict:
    """Handle MCP tools/list request."""
    generator = get_mcp_generator()
    category = params.get("category")
    if category:
        try:
            category = ServiceCategory(category)
        except ValueError:
            category = None

    manifest = await generator.generate_tools_json_async(category=category)
    return {"tools": manifest["tools"]}


async def _handle_tools_call(params: dict) -> dict:
    """
    Handle MCP tools/call request.

    This routes through the existing billing layer:
    1. Extract wallet_id from mcp_context
    2. Call the service via service registry
    3. Return the result

    For local services, we execute the function directly.
    For persistent services, we call the API endpoint.
    """
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    mcp_context = params.get("mcpContext", {})

    if not tool_name:
        raise ValueError("Missing tool name")

    wallet_id = mcp_context.get("wallet_id")
    if not wallet_id:
        raise ValueError("Missing wallet_id in mcpContext")

    registry = get_service_registry()
    service = registry.get_local(tool_name)

    if service:
        func = registry.get_local_func(tool_name)
        if func:
            import asyncio
            if asyncio.iscoroutinefunction(func):
                result = await func(**arguments)
            else:
                result = func(**arguments)

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, default=str),
                    }
                ],
                "isError": False,
            }

    raise ValueError(f"Tool not found: {tool_name}")


@router.post(
    "/tools/{service_id}/invoke",
    name="Invoke MCP Tool",
    summary="Invoke a registered MCP tool",
)
async def invoke_tool(
    service_id: str,
    request: ToolCallRequest,
    api_key: str | None = None,
) -> ToolCallResponse:
    """
    Invoke an MCP-enabled service.

    This endpoint:
    1. Verifies the API key
    2. Routes the call through the billing layer
    3. Executes the service function (local) or forwards to API (persistent)
    4. Returns the result

    For persistent services, see POST /v1/billing/services/{id}/invoke
    """
    api_key = api_key or request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    await verify_api_key(api_key)

    registry = get_service_registry()
    service = registry.get_local(service_id)

    if not service:
        service = await registry.get_persistent(service_id)
        if not service:
            raise HTTPException(status_code=404, detail=f"Service not found: {service_id}")

    mcp_context = request.mcp_context
    if not mcp_context:
        mcp_context = McpContext(wallet_id=request.arguments.get("wallet_id", ""))

    if not mcp_context.wallet_id:
        raise HTTPException(status_code=400, detail="Missing wallet_id")

    func = registry.get_local_func(service_id)
    if func:
        import asyncio
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**request.arguments)
            else:
                result = func(**request.arguments)

            return ToolCallResponse(
                content=[{"type": "text", "text": json.dumps(result, default=str)}],
                isError=False,
            )
        except Exception as e:
            logger.error(f"Tool invocation failed: {e}")
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                isError=True,
            )

    raise HTTPException(status_code=501, detail="Service not executable")


@router.get(
    "/tools",
    name="List MCP Tools",
    summary="List all available MCP tools",
)
async def list_tools(
    category: ServiceCategory | None = None,
) -> dict[str, Any]:
    """
    List all available MCP-enabled services.

    Query Parameters:
        category: Optional service category filter

    Returns:
        List of tool definitions with schemas
    """
    generator = get_mcp_generator()
    manifest = await generator.generate_tools_json_async(category=category)
    return {
        "tools": manifest["tools"],
        "count": len(manifest["tools"]),
        "generated_at": manifest["generated_at"],
    }


@router.get(
    "/tools/{service_id}",
    name="Get MCP Tool",
    summary="Get a specific MCP tool definition",
)
async def get_tool(service_id: str) -> dict[str, Any]:
    """
    Get the MCP tool definition for a specific service.

    Returns the full tool schema including:
    - inputSchema
    - outputSchema (if available)
    - pricing and category annotations
    """
    registry = get_service_registry()

    service = registry.get_local(service_id)
    if not service:
        service = await registry.get_persistent(service_id)

    if not service:
        raise HTTPException(status_code=404, detail=f"Service not found: {service_id}")

    generator = get_mcp_generator()
    tool = generator._service_to_mcp_tool(service)
    return tool
