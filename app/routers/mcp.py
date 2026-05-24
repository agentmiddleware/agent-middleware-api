"""
MCP Router
==========

Dynamic MCP Proxy router for the B2A Service Marketplace.

Provides:
- /mcp/tools.json - MCP manifest discovery
- /mcp/sse - Server-Sent Events transport
- /mcp/messages - JSON-RPC message handling

This enables agents to:
1. Discover available tools via tools.json
2. Execute tools with automatic billing + velocity monitoring
3. Receive results in real-time via SSE
"""

import inspect
import json
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..audit.lightweight import record_audit
from ..core.config import get_settings
from ..core.auth import AuthContext, get_auth_context
from ..services.service_registry import get_service_registry
from ..services.mcp_generator import get_mcp_generator
from ..services.mcp_phase9_tools import (
    ensure_phase9_registered,
    register_default_mcp_services,
)
from ..services.paid_pilot_mcp_tools import sync_paid_pilot_mcp_tools
from ..schemas.billing import InsufficientFundsResponse, ServiceCategory

# Spine primitives are consumed through the trust-plane facade so the governed
# invocation path depends on the product core by its public boundary.
from ..trust import (
    DEFAULT_PRICING,
    AgentMoney,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    McpGovernedAdapter,
    PolicyDecision,
    evaluate_tool_invocation,
    evaluate_wallet_policy,
    get_agent_money,
    get_idempotency_service,
    get_permit_service,
    get_receipt_service,
    record_audit_event,
    sha256_hex,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/mcp", tags=["MCP"])

# The MCP transport drives the governed pipeline through the protocol-neutral
# adapter seam. The adapter delegates to _execute_registered_tool below, so
# there is exactly one governance implementation.
_mcp_adapter = McpGovernedAdapter()


def _ensure_local_mcp_tools_registered() -> None:
    """Keep discovery populated when tests or transports skip app lifespan startup."""
    ensure_phase9_registered()
    register_default_mcp_services()
    sync_paid_pilot_mcp_tools()


async def build_mcp_tools_manifest(
    category: ServiceCategory | None = None,
) -> dict[str, Any]:
    """Build the canonical MCP tools manifest for all public discovery routes."""
    _ensure_local_mcp_tools_registered()
    generator = get_mcp_generator()
    return await generator.generate_tools_json_async(category=category)


class ToolExecutionError(RuntimeError):
    """Raised after a dispatched tool fails and compensation is complete."""


class GovernedToolError(RuntimeError):
    """Terminal governed-call error that can carry a signed receipt."""

    def __init__(
        self,
        reason: str,
        *,
        receipt: dict[str, Any] | None = None,
        status_code: int = 500,
        jsonrpc_code: int = -32603,
    ) -> None:
        super().__init__(reason)
        self.receipt = receipt
        self.status_code = status_code
        self.jsonrpc_code = jsonrpc_code


class ToolPermissionDenied(PermissionError):
    """Permission denial that may carry a signed receipt for governed calls."""

    def __init__(
        self,
        reason: str,
        receipt: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.receipt = receipt
        self.status_code = 403
        self.jsonrpc_code = -32003


class McpContext(BaseModel):
    """MCP execution context passed in tool calls."""

    wallet_id: str = Field(..., description="Wallet to charge for this call")
    request_path: str | None = Field(
        None, description="Optional request path for tracking"
    )
    permit_id: str | None = Field(None, description="Signed permit for governed calls")
    idempotency_key: str | None = Field(
        None, description="Replay key for governed calls"
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
    receipt: dict[str, Any] | None = None


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
    manifest = await build_mcp_tools_manifest(category=category)
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
        mcp_context = params.get("mcpContext", {}) or {}
        try:
            result = await _handle_tools_call(
                params,
                auth=auth,
                money=money,
                transport="jsonrpc",
                endpoint="/mcp/messages",
                request_id=str(request_id) if request_id is not None else None,
                idempotency_key=mcp_context.get("idempotency_key")
                or request.headers.get("Idempotency-Key"),
                request_payload=body,
            )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
            )
        except ToolPermissionDenied as e:
            error_payload: dict[str, Any] = {
                "code": -32003,
                "message": str(e),
            }
            if e.receipt:
                error_payload["data"] = {"receipt": e.receipt}
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": error_payload,
                }
            )
        except GovernedToolError as e:
            error_payload = {
                "code": e.jsonrpc_code,
                "message": str(e),
            }
            if e.receipt:
                error_payload["data"] = {"receipt": e.receipt}
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": error_payload,
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
        except ValueError as e:
            code = _value_error_jsonrpc_code(str(e))
            if code == -32603:
                logger.error(f"MCP tool call failed: {e}")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": code,
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
    category = params.get("category")
    if category:
        try:
            category = ServiceCategory(category)
        except ValueError:
            category = None

    manifest = await build_mcp_tools_manifest(category=category)
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
    permit_id: str | None = None,
    idempotency_key: str | None = None,
    request_payload: dict[str, Any] | None = None,
) -> dict:
    if not tool_name:
        raise ValueError("Missing tool name")
    if not wallet_id:
        raise ValueError("Missing wallet_id in mcpContext")

    governed_call = bool(permit_id) or (
        settings.TRUST_MODE_ENABLED and not settings.ALLOW_LEGACY_UNPERMITTED_MCP
    )
    idem = get_idempotency_service()
    replay = None
    idem_started = False
    if governed_call and idempotency_key:
        try:
            replay = await idem.begin(
                wallet_id=wallet_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_payload=request_payload
                or {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "wallet_id": wallet_id,
                    "permit_id": permit_id,
                },
            )
            idem_started = True
        except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
            raise ValueError(str(exc)) from exc
        if replay and replay.response_json:
            _raise_replayed_error(replay)
            return replay.response_json

    _ensure_local_mcp_tools_registered()
    registry = get_service_registry()
    service = registry.get_local(tool_name)
    if not service:
        service = await registry.get_persistent(tool_name)
    if not service:
        reason = f"Tool not found: {tool_name}"
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            reason=reason,
            status_code=400,
        )
        raise ValueError(reason)

    func = registry.get_local_func(tool_name)
    if not func:
        reason = f"Tool not executable: {tool_name}"
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            reason=reason,
            status_code=400,
        )
        raise ValueError(reason)

    category = ServiceCategory(
        service.get("category", ServiceCategory.PLATFORM_FEE.value)
    )
    registered_cost = _registered_tool_cost(service, category)
    charge_units = _charge_units_for_registered_cost(registered_cost, category)
    estimated_cost = float(registered_cost)

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

    if governed_call and not permit_id:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error="permit_required",
            extra_metadata={
                "idempotency_key": idempotency_key,
                "request_hash": sha256_hex(request_payload or arguments),
            },
        )
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            reason="permit_required",
        )
        raise PermissionError("permit_required")
    if governed_call and not idempotency_key:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error="idempotency_key_required",
            extra_metadata={
                "permit_id": permit_id,
                "request_hash": sha256_hex(request_payload or arguments),
            },
        )
        raise ValueError("idempotency_key_required")

    if governed_call and idempotency_key and not idem_started:
        try:
            replay = await idem.begin(
                wallet_id=wallet_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_payload=request_payload
                or {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "wallet_id": wallet_id,
                    "permit_id": permit_id,
                },
            )
        except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
            await _audit_mcp_invocation(
                decision=decision,
                endpoint=endpoint,
                transport=transport,
                ok=False,
                error=str(exc),
                extra_metadata={
                    "permit_id": permit_id,
                    "idempotency_key": idempotency_key,
                    "request_hash": sha256_hex(request_payload or arguments),
                },
            )
            raise ValueError(str(exc))
        if replay and replay.response_json:
            _raise_replayed_error(replay)
            return replay.response_json

    permit_model = None
    if governed_call:
        permit_validation = await get_permit_service().validate_for_action(
            permit_id=permit_id or "",
            wallet_id=wallet_id,
            tool_name=tool_name,
            estimated_credits=registered_cost,
            key_id=auth.key_id,
        )
        permit_model = permit_validation.permit
        if not permit_validation.allowed:
            audit_event = await _audit_mcp_invocation(
                decision=decision,
                endpoint=endpoint,
                transport=transport,
                ok=False,
                error=permit_validation.reason,
                extra_metadata={
                    "permit_id": permit_id,
                    "idempotency_key": idempotency_key,
                    "request_hash": sha256_hex(request_payload or arguments),
                },
            )
            receipt_payload = None
            reason = permit_validation.reason or "permit_denied"
            if permit_model:
                receipt_payload = await _finalize_governed_denial(
                    idem=idem,
                    permit_model=permit_model,
                    wallet_id=wallet_id,
                    key_id=auth.key_id,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    request_payload=request_payload,
                    arguments=arguments,
                    registered_cost=registered_cost,
                    audit_event_id=audit_event.event_id,
                    reason=reason,
                    outcome="denied",
                    status_code=403,
                )
            elif permit_validation.reason:
                await _complete_governed_denial_idempotency(
                    idem=idem,
                    idem_started=idem_started,
                    wallet_id=wallet_id,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    reason=permit_validation.reason,
                )
            raise ToolPermissionDenied(reason, receipt=receipt_payload)

    simulation = False
    try:
        from ..core.runtime_mode import is_simulation

        simulation = is_simulation(category.value)
    except Exception as exc:
        # Default to real-effects (simulation=False) but surface the
        # misconfiguration instead of swallowing it silently.
        logger.warning(
            "runtime_mode_check_failed",
            extra={"category": category.value, "error": str(exc)},
        )
        simulation = False
    policy = await evaluate_wallet_policy(
        wallet_id=wallet_id,
        tool_name=tool_name,
        service_category=category.value,
        estimated_cost=registered_cost,
        daily_spend_used=await money.get_daily_spend(wallet_id),
        simulation=simulation,
    )
    policy_metadata = {
        "policy_id": policy.policy_id,
        "evaluated_constraints": policy.evaluated_constraints,
    }
    if not policy.allowed:
        trust_metadata = _trust_metadata(
            permit_id=permit_id,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            arguments=arguments,
        )
        audit_event = await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=policy.reason,
            extra_metadata={**policy_metadata, **trust_metadata},
        )
        if governed_call and permit_model:
            reason = policy.reason or "policy_denied"
            receipt_payload = await _finalize_governed_denial(
                idem=idem,
                permit_model=permit_model,
                wallet_id=wallet_id,
                key_id=auth.key_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                request_payload=request_payload,
                arguments=arguments,
                registered_cost=registered_cost,
                audit_event_id=audit_event.event_id,
                reason=reason,
                outcome="denied",
                status_code=403,
            )
            raise ToolPermissionDenied(reason, receipt=receipt_payload)
        raise PermissionError(policy.reason)

    description = f"MCP {transport} invoke {tool_name}"
    if governed_call and permit_model:
        await get_permit_service().reserve_budget(
            permit_model.permit_id, registered_cost
        )
    charge_result = await money.charge(
        wallet_id=wallet_id,
        service_category=category,
        units=charge_units,
        request_path=endpoint,
        description=description,
    )
    if isinstance(charge_result, InsufficientFundsResponse):
        if governed_call and permit_model:
            await get_permit_service().release_budget(
                permit_model.permit_id,
                registered_cost,
            )
        audit_event = await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error="insufficient_funds",
            extra_metadata={
                **policy_metadata,
                **_trust_metadata(
                    permit_id=permit_id,
                    idempotency_key=idempotency_key,
                    request_payload=request_payload,
                    arguments=arguments,
                ),
            },
        )
        if governed_call and permit_model:
            receipt_payload = await _finalize_governed_denial(
                idem=idem,
                permit_model=permit_model,
                wallet_id=wallet_id,
                key_id=auth.key_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                request_payload=request_payload,
                arguments=arguments,
                registered_cost=registered_cost,
                audit_event_id=audit_event.event_id,
                reason="insufficient_funds",
                outcome="insufficient_funds",
                status_code=402,
            )
            raise GovernedToolError(
                "insufficient_funds",
                receipt=receipt_payload,
                status_code=402,
                jsonrpc_code=-32004,
            )
        raise ValueError("insufficient_funds")

    tool_arguments = {
        key: value for key, value in arguments.items() if key != "_mcp_context"
    }
    if "_mcp_context" in inspect.signature(func).parameters:
        tool_arguments["_mcp_context"] = {
            "wallet_id": wallet_id,
            "key_id": auth.key_id,
            "request_id": request_id,
            "permit_id": permit_id,
            "idempotency_key": idempotency_key,
        }

    try:
        if inspect.iscoroutinefunction(func):
            result = await func(**tool_arguments)
        else:
            result = func(**tool_arguments)
    except Exception as exc:
        try:
            await money.refund_charge(
                wallet_id=wallet_id,
                charge_entry_id=charge_result.entry_id,
                description=f"Refund {description}",
            )
        except Exception as refund_exc:
            if governed_call and permit_model:
                await get_permit_service().release_budget(
                    permit_model.permit_id,
                    registered_cost,
                )
            error = f"refund_failed:{refund_exc}; tool_error:{exc}"
            logger.error(
                "Failed to refund MCP charge %s after tool error: %s",
                charge_result.entry_id,
                refund_exc,
            )
            try:
                await _audit_mcp_invocation(
                    decision=decision,
                    endpoint=endpoint,
                    transport=transport,
                    ok=False,
                    error=error,
                    extra_metadata=policy_metadata,
                )
            except Exception as audit_exc:
                error = f"{error}; audit_failed:{audit_exc}"
                logger.error(
                    "Failed to audit MCP refund failure for charge %s: %s",
                    charge_result.entry_id,
                    audit_exc,
                )
            raise RuntimeError(error) from refund_exc
        if governed_call and permit_model:
            await get_permit_service().release_budget(
                permit_model.permit_id,
                registered_cost,
            )
        audit_event = await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=str(exc),
            extra_metadata={
                **policy_metadata,
                **_trust_metadata(
                    permit_id=permit_id,
                    idempotency_key=idempotency_key,
                    request_payload=request_payload,
                    arguments=arguments,
                    ledger_entry_id=charge_result.entry_id,
                ),
            },
        )
        if governed_call and permit_model:
            receipt_payload = await _finalize_governed_denial(
                idem=idem,
                permit_model=permit_model,
                wallet_id=wallet_id,
                key_id=auth.key_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                request_payload=request_payload,
                arguments=arguments,
                registered_cost=registered_cost,
                audit_event_id=audit_event.event_id,
                reason=str(exc),
                outcome="failed_refunded",
                status_code=500,
                ledger_entry_id=charge_result.entry_id,
            )
            raise GovernedToolError(
                str(exc),
                receipt=receipt_payload,
                status_code=500,
                jsonrpc_code=-32603,
            ) from exc
        raise ToolExecutionError(str(exc)) from exc

    response_payload = {
        "content": [{"type": "text", "text": json.dumps(result, default=str)}],
        "isError": False,
    }
    audit_event = await _audit_mcp_invocation(
        decision=decision,
        endpoint=endpoint,
        transport=transport,
        ok=True,
        error=None,
        extra_metadata={
            **policy_metadata,
            **_trust_metadata(
                permit_id=permit_id,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                arguments=arguments,
                ledger_entry_id=charge_result.entry_id,
            ),
        },
    )
    if governed_call and permit_model:
        receipt = await get_receipt_service().create_receipt(
            permit_id=permit_model.permit_id,
            wallet_id=wallet_id,
            key_id=auth.key_id,
            tool=tool_name,
            request_payload=request_payload or arguments,
            response_payload=response_payload,
            ledger_entry_id=charge_result.entry_id,
            credits_authorized=registered_cost,
            credits_charged=registered_cost,
            outcome="success",
            audit_event_id=audit_event.event_id,
        )
        response_payload["receipt"] = _receipt_response_payload(receipt)
        await idem.complete(
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key or "",
            response_reference=receipt.receipt_id,
            response_json=response_payload,
            status_code=200,
        )
    return response_payload


def _registered_tool_cost(
    service: dict[str, Any],
    category: ServiceCategory,
) -> Decimal:
    default_price = DEFAULT_PRICING[category][1]
    return Decimal(str(service.get("credits_per_unit", default_price)))


def _charge_units_for_registered_cost(
    registered_cost: Decimal,
    category: ServiceCategory,
) -> Decimal:
    default_price = DEFAULT_PRICING[category][1]
    return registered_cost / default_price


def _receipt_response_payload(receipt: Any) -> dict[str, Any]:
    payload = receipt.model_dump(mode="json")
    charged = payload.get("credits_charged")
    if charged is not None and Decimal(str(charged)) == Decimal("0"):
        payload["credits_charged"] = "0"
    return payload


def _governed_error_payload(
    reason: str,
    receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "content": [],
        "isError": True,
        "error": reason,
        "receipt": receipt,
    }


async def _complete_governed_denial_idempotency(
    *,
    idem: Any,
    idem_started: bool,
    wallet_id: str,
    endpoint: str,
    idempotency_key: str | None,
    reason: str,
    status_code: int = 403,
) -> None:
    if not idem_started or not idempotency_key:
        return
    await idem.complete(
        wallet_id=wallet_id,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        response_reference=None,
        response_json=_governed_error_payload(reason, None),
        status_code=status_code,
    )


async def _finalize_governed_denial(
    *,
    idem: Any,
    permit_model: Any,
    wallet_id: str,
    key_id: str | None,
    endpoint: str,
    idempotency_key: str | None,
    tool_name: str,
    request_payload: dict[str, Any] | None,
    arguments: dict[str, Any],
    registered_cost: Decimal,
    audit_event_id: str,
    reason: str,
    outcome: str,
    status_code: int,
    ledger_entry_id: str | None = None,
) -> dict[str, Any]:
    """Sign a non-success governed receipt and record the idempotent outcome.

    Shared by every governed terminal-failure branch (permit denied, policy
    denied, insufficient funds, tool execution failure) so the receipt contract
    and idempotency completion are written in exactly one place.
    """
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit_model.permit_id,
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool_name,
        request_payload=request_payload or arguments,
        response_payload={"error": reason},
        ledger_entry_id=ledger_entry_id,
        credits_authorized=registered_cost,
        credits_charged=Decimal("0"),
        outcome=outcome,
        audit_event_id=audit_event_id,
    )
    receipt_payload = _receipt_response_payload(receipt)
    await idem.complete(
        wallet_id=wallet_id,
        endpoint=endpoint,
        idempotency_key=idempotency_key or "",
        response_reference=receipt.receipt_id,
        response_json=_governed_error_payload(reason, receipt_payload),
        status_code=status_code,
    )
    return receipt_payload


def _raise_replayed_error(replay: Any) -> None:
    if replay.status_code < 400 or not replay.response_json:
        return
    reason = str(replay.response_json.get("error") or "governed_call_failed")
    receipt = replay.response_json.get("receipt")
    if replay.status_code == 403:
        raise ToolPermissionDenied(reason, receipt=receipt)
    raise GovernedToolError(
        reason,
        receipt=receipt,
        status_code=replay.status_code,
        jsonrpc_code=_status_to_jsonrpc_code(replay.status_code, reason),
    )


def _status_to_jsonrpc_code(status_code: int, reason: str) -> int:
    if status_code == 402 or reason == "insufficient_funds":
        return -32004
    if reason.startswith("Tool not found"):
        return -32001
    if reason.startswith("Tool not executable"):
        return -32002
    if status_code == 403:
        return -32003
    return -32603


def _trust_metadata(
    *,
    permit_id: str | None,
    idempotency_key: str | None,
    request_payload: dict[str, Any] | None,
    arguments: dict[str, Any],
    ledger_entry_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "request_hash": sha256_hex(request_payload or arguments),
    }
    if permit_id:
        metadata["permit_id"] = permit_id
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    if ledger_entry_id:
        metadata["ledger_entry_id"] = ledger_entry_id
    return metadata


def _value_error_jsonrpc_code(message: str) -> int:
    if message in {"Missing tool name", "Missing wallet_id in mcpContext"}:
        return -32602
    if message.startswith("Tool not found"):
        return -32001
    if message.startswith("Tool not executable"):
        return -32002
    if message == "idempotency_key_required":
        return -32003
    if message == "idempotency_in_progress":
        return -32003
    if message == "insufficient_funds":
        return -32004
    return -32603


async def _audit_mcp_invocation(
    *,
    decision: PolicyDecision,
    endpoint: str,
    transport: str,
    ok: bool,
    error: str | None,
    extra_metadata: dict[str, Any] | None = None,
) -> Any:
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
    return await record_audit_event(
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
            **(extra_metadata or {}),
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
    idempotency_key: str | None = None,
    request_payload: dict[str, Any] | None = None,
) -> dict:
    governed_request = await _mcp_adapter.normalize_request(
        params,
        auth=auth,
        money=money,
        transport=transport,
        endpoint=endpoint,
        request_id=request_id,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    result = await _mcp_adapter.invoke(governed_request)
    return await _mcp_adapter.normalize_response(result)


@router.post(
    "/tools/{service_id}/invoke",
    name="Invoke MCP Tool",
    summary="Invoke a registered MCP tool",
)
async def invoke_tool(
    service_id: str,
    request: ToolCallRequest,
    http_request: Request,
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

    mcp_payload = {
        "name": service_id,
        "arguments": request.arguments,
        "mcpContext": {
            "wallet_id": mcp_context.wallet_id,
            "permit_id": mcp_context.permit_id,
            "idempotency_key": mcp_context.idempotency_key,
        },
    }
    try:
        governed_request = await _mcp_adapter.normalize_request(
            mcp_payload,
            auth=auth,
            money=money,
            transport="http",
            endpoint=f"/mcp/tools/{service_id}/invoke",
            request_id=None,
            idempotency_key=mcp_context.idempotency_key
            or http_request.headers.get("Idempotency-Key"),
            request_payload=request.model_dump(mode="json"),
        )
        result = await _mcp_adapter.invoke(governed_request)
        return ToolCallResponse(**await _mcp_adapter.normalize_response(result))
    except ToolPermissionDenied as exc:
        detail: dict[str, Any] = {"error": str(exc)}
        if exc.receipt:
            detail["receipt"] = exc.receipt
        raise HTTPException(status_code=403, detail=detail)
    except GovernedToolError as exc:
        detail = {"error": str(exc)}
        if exc.receipt:
            detail["receipt"] = exc.receipt
        raise HTTPException(status_code=exc.status_code, detail=detail)
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
    manifest = await build_mcp_tools_manifest(category=category)
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
    _ensure_local_mcp_tools_registered()
    registry = get_service_registry()

    service = registry.get_local(service_id)
    if not service:
        service = await registry.get_persistent(service_id)

    if not service:
        raise HTTPException(status_code=404, detail=f"Service not found: {service_id}")

    generator = get_mcp_generator()
    tool = generator._service_to_mcp_tool(service)
    return tool
