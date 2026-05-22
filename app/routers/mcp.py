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

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..audit.lightweight import record_audit
from ..core.auth import AuthContext, get_auth_context
from ..core.config import get_settings
from ..services.service_registry import get_service_registry
from ..services.mcp_generator import get_mcp_generator
from ..services.permits import PermitError, require_permit_for_tool
from ..schemas.billing import ServiceCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP"])


def _permit_enforcement_enabled() -> bool:
    return get_settings().PERMITS_ENFORCED


class McpContext(BaseModel):
    """MCP execution context passed in tool calls."""

    wallet_id: str = Field(..., description="Wallet to charge for this call")
    request_path: str | None = Field(
        None, description="Optional request path for tracking"
    )


class ToolCallRequest(BaseModel):
    """MCP tool call request (tools/call method)."""

    name: str = Field(..., description="Tool name (service_id)")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )
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
async def handle_messages(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> JSONResponse:
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
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        )

    elif method == "tools/call":
        try:
            permit_token = request.headers.get(get_settings().PERMIT_HEADER)
            result = await _handle_tools_call(params, auth, permit_token)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e),
                    },
                }
            )

    else:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }
        )


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


async def _handle_tools_call(
    params: dict, auth: AuthContext, permit_token: str | None = None
) -> dict:
    """
    Handle MCP tools/call request.

    This routes through the existing billing layer:
    1. Extract wallet_id from mcp_context
    2. Enforce a capability permit when PERMITS_ENFORCED is set
    3. Call the service via service registry
    4. Return the result

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
    auth.require_wallet_access(wallet_id)

    if _permit_enforcement_enabled():
        local_service = get_service_registry().get_local(tool_name)
        tool_cost = (
            float(local_service.get("credits_per_unit", 1.0)) if local_service else 0.0
        )
        try:
            await require_permit_for_tool(
                permit_token,
                wallet_id=wallet_id,
                tool_name=tool_name,
                cost=tool_cost,
            )
        except PermitError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "permit_denied", "reason": str(exc)},
            )

    ok = False
    err: str | None = None
    try:
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

                ok = True
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, default=str),
                        }
                    ],
                    "isError": False,
                }

        err = f"Tool not found: {tool_name}"
        raise ValueError(err)
    except Exception as exc:
        if err is None:
            err = str(exc)
        raise
    finally:
        record_audit(
            "mcp.tools.call",
            tool=tool_name,
            wallet_id=wallet_id,
            transport="jsonrpc",
            auth_source=auth.source,
            key_id=auth.key_id,
            ok=ok,
            error=err,
        )


@router.post(
    "/tools/{service_id}/invoke",
    name="Invoke MCP Tool",
    summary="Invoke a registered MCP tool",
)
async def invoke_tool(
    service_id: str,
    request: ToolCallRequest,
    raw_request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> ToolCallResponse:
    """
    Invoke an MCP-enabled service.

    This endpoint:
    1. Verifies the API key
    2. Enforces a capability permit when PERMITS_ENFORCED is set
    3. Routes the call through the billing layer
    4. Executes the service function (local) or forwards to API (persistent)
    5. Returns the result

    For persistent services, see POST /v1/billing/services/{id}/invoke
    """
    registry = get_service_registry()
    service = registry.get_local(service_id)

    if not service:
        service = await registry.get_persistent(service_id)
        if not service:
            raise HTTPException(
                status_code=404, detail=f"Service not found: {service_id}"
            )

    mcp_context = request.mcp_context
    if not mcp_context:
        mcp_context = McpContext(wallet_id=request.arguments.get("wallet_id", ""))

    if not mcp_context.wallet_id:
        raise HTTPException(status_code=400, detail="Missing wallet_id")
    auth.require_wallet_access(mcp_context.wallet_id)

    if _permit_enforcement_enabled():
        tool_cost = (
            float(service.get("credits_per_unit", 1.0))
            if isinstance(service, dict)
            else 1.0
        )
        permit_token = raw_request.headers.get(get_settings().PERMIT_HEADER)
        try:
            await require_permit_for_tool(
                permit_token,
                wallet_id=mcp_context.wallet_id,
                tool_name=service_id,
                cost=tool_cost,
            )
        except PermitError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": "permit_denied", "reason": str(exc)},
            )

    func = registry.get_local_func(service_id)
    if func:
        import asyncio

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**request.arguments)
            else:
                result = func(**request.arguments)

            record_audit(
                "mcp.http.invoke",
                tool=service_id,
                wallet_id=mcp_context.wallet_id,
                auth_source=auth.source,
                key_id=auth.key_id,
                ok=True,
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": json.dumps(result, default=str)}],
                isError=False,
            )
        except Exception as e:
            logger.error(f"Tool invocation failed: {e}")
            record_audit(
                "mcp.http.invoke",
                tool=service_id,
                wallet_id=mcp_context.wallet_id,
                auth_source=auth.source,
                key_id=auth.key_id,
                ok=False,
                error=str(e),
            )
            return ToolCallResponse(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                isError=True,
            )

    raise HTTPException(status_code=501, detail="Service not executable")


@router.get(
    "/tools",
    name="List MCP Tools",
    summary="List all available MCP tools (paginated)",
)
async def list_tools(
    category: ServiceCategory | None = None,
    limit: int = Query(default=100, ge=1, le=500, description="Max tools to return"),
    offset: int = Query(default=0, ge=0, description="Number of tools to skip"),
) -> dict[str, Any]:
    """
    List all available MCP-enabled services with pagination.

    Query Parameters:
        category: Optional service category filter
        limit: Maximum number of tools to return (default 100, max 500)
        offset: Number of tools to skip for pagination

    Returns:
        Paginated list of tool definitions with schemas
    """
    generator = get_mcp_generator()
    manifest = await generator.generate_tools_json_async(category=category)
    tools = manifest["tools"]
    total = len(tools)

    paginated_tools = tools[offset : offset + limit]

    return {
        "tools": paginated_tools,
        "count": len(paginated_tools),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(paginated_tools) < total,
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
