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
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..audit.lightweight import record_audit
from ..core.auth import AuthContext, get_auth_context
from ..policy.decisions import PolicyDecision, evaluate_tool_invocation
from ..services.agent_money import AgentMoney, get_agent_money
from ..services.audit_log import record_audit_event
from ..services.service_registry import get_service_registry
from ..services.mcp_generator import get_mcp_generator
from ..schemas.billing import InsufficientFundsResponse, ServiceCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP"])


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
    money: AgentMoney = Depends(get_agent_money),
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
            result = await _handle_tools_call(
                params,
                auth=auth,
                money=money,
                transport="jsonrpc",
                endpoint="/mcp/messages",
                request_id=str(request_id) if request_id is not None else None,
            )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
            )
        except PermissionError as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32003,
                        "message": str(e),
                    },
                }
            )
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


async def _execute_registered_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    wallet_id: str,
    auth: AuthContext,
    money: AgentMoney,
    transport: str,
    endpoint: str,
    request_id: str | None,
) -> dict:
    if not tool_name:
        raise ValueError("Missing tool name")
    if not wallet_id:
        raise ValueError("Missing wallet_id in mcpContext")

    registry = get_service_registry()
    service = registry.get_local(tool_name)
    if not service:
        service = await registry.get_persistent(tool_name)
    if not service:
        raise ValueError(f"Tool not found: {tool_name}")

    func = registry.get_local_func(tool_name)
    if not func:
        raise ValueError(f"Tool not executable: {tool_name}")

    estimated_cost = float(service.get("credits_per_unit", 1.0))
    decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id=wallet_id,
        tool_name=tool_name,
        estimated_cost=estimated_cost,
        request_id=request_id,
    )
    if not decision.allowed:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=decision.reason,
        )
        raise PermissionError(decision.reason)

    category = ServiceCategory(
        service.get("category", ServiceCategory.PLATFORM_FEE.value)
    )
    charge_result = await money.charge(
        wallet_id=wallet_id,
        service_category=category,
        units=Decimal("1"),
        request_path=endpoint,
        description=f"MCP {transport} invoke {tool_name}",
    )
    if isinstance(charge_result, InsufficientFundsResponse):
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error="insufficient_funds",
        )
        raise ValueError("insufficient_funds")

    import asyncio

    try:
        if asyncio.iscoroutinefunction(func):
            result = await func(**arguments)
        else:
            result = func(**arguments)
    except Exception as exc:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=str(exc),
        )
        raise

    await _audit_mcp_invocation(
        decision=decision,
        endpoint=endpoint,
        transport=transport,
        ok=True,
        error=None,
    )
    return {
        "content": [{"type": "text", "text": json.dumps(result, default=str)}],
        "isError": False,
    }


async def _audit_mcp_invocation(
    *,
    decision: PolicyDecision,
    endpoint: str,
    transport: str,
    ok: bool,
    error: str | None,
) -> None:
    record_audit(
        "mcp.invoke",
        tool=decision.tool_name,
        wallet_id=decision.wallet_id,
        transport=transport,
        auth_source=decision.auth_source,
        key_id=decision.key_id,
        policy_decision_id=decision.decision_id,
        request_id=decision.request_id,
        ok=ok,
        error=error,
    )
    await record_audit_event(
        event="mcp.invoke",
        wallet_id=decision.wallet_id,
        tool=decision.tool_name,
        endpoint=endpoint,
        auth_source=decision.auth_source,
        key_id=decision.key_id,
        policy_decision_id=decision.decision_id,
        request_id=decision.request_id,
        ok=ok,
        error=error,
        metadata={
            "transport": transport,
            "estimated_cost": decision.estimated_cost,
            "policy_reason": decision.reason,
        },
    )


async def _handle_tools_call(
    params: dict,
    *,
    auth: AuthContext,
    money: AgentMoney,
    transport: str,
    endpoint: str,
    request_id: str | None,
) -> dict:
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    mcp_context = params.get("mcpContext", {})
    wallet_id = mcp_context.get("wallet_id")
    return await _execute_registered_tool(
        tool_name=tool_name,
        arguments=arguments,
        wallet_id=wallet_id,
        auth=auth,
        money=money,
        transport=transport,
        endpoint=endpoint,
        request_id=request_id,
    )


@router.post(
    "/tools/{service_id}/invoke",
    name="Invoke MCP Tool",
    summary="Invoke a registered MCP tool",
)
async def invoke_tool(
    service_id: str,
    request: ToolCallRequest,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
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
    mcp_context = request.mcp_context
    if not mcp_context:
        mcp_context = McpContext(wallet_id=request.arguments.get("wallet_id", ""))

    if not mcp_context.wallet_id:
        raise HTTPException(status_code=400, detail="Missing wallet_id")

    try:
        result = await _execute_registered_tool(
            tool_name=service_id,
            arguments=request.arguments,
            wallet_id=mcp_context.wallet_id,
            auth=auth,
            money=money,
            transport="http",
            endpoint=f"/mcp/tools/{service_id}/invoke",
            request_id=None,
        )
        return ToolCallResponse(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        message = str(exc)
        if message == "insufficient_funds":
            raise HTTPException(status_code=402, detail=message)
        if message.startswith("Tool not found"):
            raise HTTPException(status_code=404, detail=message)
        if message.startswith("Tool not executable"):
            raise HTTPException(status_code=501, detail=message)
        raise HTTPException(status_code=400, detail=message)
    except Exception as exc:
        logger.error(f"Tool invocation failed: {exc}")
        return ToolCallResponse(
            content=[{"type": "text", "text": f"Error: {str(exc)}"}],
            isError=True,
        )


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
