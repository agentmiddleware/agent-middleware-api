"""
MCP Router
==========

Governed MCP proxy for the agent trust plane (permits, metering, receipts).

Provides:
- /mcp/tools.json - MCP manifest discovery
- /mcp/sse - Server-Sent Events transport
- /mcp/messages - JSON-RPC message handling

This enables agents to:
1. Discover ops-registered tools via tools.json
2. Invoke tools under permit + wallet metering + signed receipts
3. Receive results in real-time via SSE
"""

import asyncio
import inspect
import json
import logging
from decimal import Decimal
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from ..audit.lightweight import record_audit
from ..core.config import get_settings
from ..core.auth import AuthContext, get_auth_context
from ..services.service_registry import get_service_registry
from ..services.mcp_generator import get_mcp_generator
from ..services.dogfood_tool import sync_dogfood_tool_registration
from ..services.mcp_phase9_tools import sync_proof_surface_mcp_registration
from ..services.mcp_dispatch_attempts import (
    DispatchResultRejectedError,
    DispatchResultTooLargeError,
    McpDispatchAttemptService,
    get_mcp_dispatch_attempt_service,
)
from ..services.mcp_dispatch_reconciliation import (
    get_mcp_dispatch_reconciliation_service,
)
from ..services.upstream_mcp import (
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpPreDispatchError,
    UpstreamMcpResponseRejectedError,
    UpstreamMcpReturnedError,
)
from ..schemas.billing import InsufficientFundsResponse, LedgerEntry, ServiceCategory

# Spine primitives are consumed through the trust-plane facade so the governed
# invocation path depends on the product core by its public boundary.
from ..trust import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_PENDING,
    DEFAULT_PRICING,
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    AgentMoney,
    HumanApprovalError,
    HumanApprovalUnavailableError,
    IdempotencyBegin,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    McpGovernedAdapter,
    PolicyDecision,
    evaluate_tool_invocation,
    evaluate_wallet_policy,
    get_agent_money,
    get_human_approval_service,
    get_idempotency_service,
    get_permit_service,
    get_receipt_service,
    record_audit_event,
    get_refund_reconciliation_service,
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
    """Align local MCP tools with proof-surface + dogfood flags (lazy + flag flips)."""
    sync_proof_surface_mcp_registration()
    sync_dogfood_tool_registration()


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
        extra_data: dict[str, Any] | None = None,
        status_code: int = 500,
        jsonrpc_code: int = -32603,
    ) -> None:
        super().__init__(reason)
        self.receipt = receipt
        self.extra_data = extra_data or {}
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


class HumanApprovalPendingSignal(RuntimeError):
    """Governed invoke paused on a retryable human-approval condition.

    Not a terminal outcome: no receipt exists, nothing was charged, and the
    caller's idempotency key was released — the same invoke (same body, same
    key) should be retried once the approval is decided (or, for
    ``human_approval_unavailable``, once Sentinel is reachable again).
    """

    jsonrpc_code = -32005

    def __init__(
        self,
        reason: str,
        *,
        data: dict[str, Any] | None = None,
        status_code: int = 202,
    ) -> None:
        super().__init__(reason)
        self.data = data or {}
        self.status_code = status_code


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
    structuredContent: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None


@router.get("/tools.json", name="MCP Tools Manifest")
async def get_tools_json(
    category: ServiceCategory | None = None,
) -> JSONResponse:
    """
    Return the MCP tools.json manifest.

    This is an unauthenticated HTTP mirror of tool metadata exposed by this
    project's governed JSON-RPC subset. Clients can obtain the same list by
    sending ``tools/list`` to ``/mcp/messages``; that endpoint does not
    implement the complete MCP initialization lifecycle.

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
        except HumanApprovalPendingSignal as e:
            error_payload: dict[str, Any] = {
                "code": e.jsonrpc_code,
                "message": str(e),
            }
            if e.data:
                error_payload["data"] = e.data
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": error_payload,
                }
            )
        except ToolPermissionDenied as e:
            error_payload = {
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
            error_data = dict(e.extra_data)
            if e.receipt:
                error_data["receipt"] = e.receipt
            if error_data:
                error_payload["data"] = error_data
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


def _legacy_mcp_idempotency_endpoints(
    *,
    endpoint: str,
    tool_name: str,
) -> tuple[str, ...]:
    """Return the pre-canonical MCP replay scopes, current transport first."""
    candidates = (
        endpoint,
        "/mcp/messages",
        f"/mcp/tools/{tool_name}/invoke",
    )
    return tuple(
        candidate
        for candidate in dict.fromkeys(candidates)
        if candidate != GOVERNED_MCP_IDEMPOTENCY_ENDPOINT
    )


async def _begin_governed_mcp_idempotency(
    *,
    idem: Any,
    wallet_id: str,
    idempotency_key: str,
    tool_name: str,
    endpoint: str,
    logical_request_payload: dict[str, Any],
    legacy_request_payload: dict[str, Any] | None,
    operation_kind: str,
    wait_timeout_seconds: float = 0.0,
) -> IdempotencyBegin:
    """Adopt a completed pre-canonical replay without creating a new identity.

    Before migration 026, governed MCP calls were keyed by their physical REST
    or JSON-RPC endpoint and hashed the raw transport payload. A canonical row
    must not be created while either legacy scope already owns the wallet/key:
    doing so could debit and dispatch the same historical action again.

    Only the current transport payload can be compared exactly. An existing row
    under the other transport is therefore a fail-closed conflict (or remains in
    progress) rather than an unsafe cross-transport guess. Migration 027 adds a
    database identity shared by old and current workers; the second lookup below
    adopts whichever row won a rolling-deployment insertion race.
    """
    historical_payload = legacy_request_payload or logical_request_payload

    async def resolve_existing() -> IdempotencyBegin | None:
        canonical = await idem.get_record(
            wallet_id=wallet_id,
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key=idempotency_key,
        )
        if canonical is not None:
            return await idem.begin_with_record(
                wallet_id=wallet_id,
                endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                idempotency_key=idempotency_key,
                request_payload=logical_request_payload,
                operation_kind=operation_kind,
                wait_timeout_seconds=wait_timeout_seconds,
            )

        for candidate_endpoint in _legacy_mcp_idempotency_endpoints(
            endpoint=endpoint,
            tool_name=tool_name,
        ):
            existing = await idem.get_record(
                wallet_id=wallet_id,
                endpoint=candidate_endpoint,
                idempotency_key=idempotency_key,
            )
            if existing is None:
                continue
            if candidate_endpoint != endpoint:
                if existing.response_json:
                    raise IdempotencyConflictError("idempotency_key_reused")
                raise IdempotencyInProgressError("idempotency_in_progress")
            return await idem.begin_with_record(
                wallet_id=wallet_id,
                endpoint=candidate_endpoint,
                idempotency_key=idempotency_key,
                request_payload=historical_payload,
                operation_kind=operation_kind,
                wait_timeout_seconds=wait_timeout_seconds,
            )
        return None

    existing = await resolve_existing()
    if existing is not None:
        return existing

    try:
        return await idem.begin_with_record(
            wallet_id=wallet_id,
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key=idempotency_key,
            request_payload=logical_request_payload,
            operation_kind=operation_kind,
            wait_timeout_seconds=wait_timeout_seconds,
        )
    except IntegrityError:
        # The normalized unique index can reject this insert because a legacy
        # worker committed its physical-endpoint row after our initial probes.
        # Re-resolve that winner; unrelated integrity failures still propagate.
        raced = await resolve_existing()
        if raced is not None:
            return raced
        winner = await idem.get_governed_mcp_record(
            wallet_id=wallet_id,
            idempotency_key=idempotency_key,
        )
        if winner is not None:
            # A legacy REST worker for a different tool may own the normalized
            # wallet/key. Its transport hash cannot represent this request, so
            # surface a stable conflict instead of leaking a raw integrity error.
            if winner.response_json:
                raise IdempotencyConflictError("idempotency_key_reused")
            raise IdempotencyInProgressError("idempotency_in_progress")
        raise


async def _execute_registered_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    wallet_id: str | None,
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

    # Authorize wallet ownership BEFORE the idempotency store is touched. The
    # idempotency lookup key is (wallet_id, endpoint, key) with wallet_id taken
    # from the request body, so running idem.begin() first let an unauthorized
    # caller (a) be served another wallet's stored signed receipt via the replay
    # short-circuit and (b) plant an orphaned in-progress record in the victim's
    # namespace on denial, permanently poisoning that (wallet, key). Gate here so
    # a caller who does not own wallet_id never reaches the store. The priced
    # decision below re-runs this check with the real cost for the audit record.
    tenant_decision = evaluate_tool_invocation(
        auth=auth,
        wallet_id=wallet_id,
        tool_name=tool_name,
        estimated_cost=None,
        request_id=request_id,
    )
    if not tenant_decision.allowed:
        await _audit_mcp_invocation(
            decision=tenant_decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=tenant_decision.reason,
        )
        raise ToolPermissionDenied(tenant_decision.reason)

    governed_call = bool(permit_id) or (
        settings.TRUST_MODE_ENABLED and not settings.ALLOW_LEGACY_UNPERMITTED_MCP
    )
    idem = get_idempotency_service()
    idempotency_wait_seconds = max(
        1.0,
        settings.MCP_UPSTREAM_CONNECT_TIMEOUT_SECONDS
        + settings.MCP_UPSTREAM_CALL_TIMEOUT_SECONDS
        + 5.0,
    )
    # Idempotency describes the logical invocation, not transport framing.
    # In particular, JSON-RPC correlation IDs and REST-vs-JSON-RPC routing
    # must not create a second gateway dispatch for the same caller key.
    effective_request_payload = {
        "tool_name": tool_name,
        "arguments": arguments,
        "wallet_id": wallet_id,
        "permit_id": permit_id,
    }
    idempotency_endpoint = (
        GOVERNED_MCP_IDEMPOTENCY_ENDPOINT if governed_call else endpoint
    )
    effective_request_hash = sha256_hex(effective_request_payload)
    replay = None
    idem_started = False
    idem_begin: IdempotencyBegin | None = None

    _ensure_local_mcp_tools_registered()
    registry = get_service_registry()
    service = registry.get_local(tool_name)
    if not service:
        service = await registry.get_persistent(tool_name)
    if not service:
        # Durable replay is authoritative even if an operator has since
        # removed the executable registration. This is essential for terminal
        # evidence recovery and avoids turning a completed invocation into a
        # fresh "not found" response after restart or reconfiguration.
        if governed_call and idempotency_key:
            try:
                idem_begin = await _begin_governed_mcp_idempotency(
                    idem=idem,
                    wallet_id=wallet_id,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    endpoint=endpoint,
                    logical_request_payload=effective_request_payload,
                    legacy_request_payload=request_payload,
                    operation_kind="unresolved",
                )
                replay = idem_begin.replay
                idem_started = True
            except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
                raise ValueError(str(exc)) from exc
            if replay and replay.response_json:
                if permit_id:
                    await _assert_governed_replay_access(
                        permit_id=permit_id,
                        wallet_id=wallet_id,
                        tool_name=tool_name,
                        key_id=auth.key_id,
                    )
                await _raise_replayed_error(replay)
                return replay.response_json
        reason = f"Tool not found: {tool_name}"
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            reason=reason,
            status_code=400,
        )
        raise ValueError(reason)

    execution_backend = str(service.get("execution_backend") or "metadata_only")
    func = registry.get_local_func(tool_name)
    upstream_executor = registry.get_executor(tool_name)
    if execution_backend == "local" and func is None:
        reason = f"Tool not executable: {tool_name}"
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            reason=reason,
            status_code=400,
        )
        raise ValueError(reason)
    if execution_backend == "upstream_mcp" and upstream_executor is None:
        reason = f"Tool not executable: {tool_name}"
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            reason=reason,
            status_code=400,
        )
        raise ValueError(reason)
    if execution_backend not in {"local", "upstream_mcp"}:
        reason = f"Tool not executable: {tool_name}"
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            reason=reason,
            status_code=400,
        )
        raise ValueError(reason)

    category = ServiceCategory(
        service.get("category", ServiceCategory.PLATFORM_FEE.value)
    )
    # High-value tools can force the permit path even when legacy
    # unpermitted MCP is otherwise allowed.
    if service.get("require_permit"):
        governed_call = True
    if governed_call:
        idempotency_endpoint = GOVERNED_MCP_IDEMPOTENCY_ENDPOINT

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
                "request_hash": effective_request_hash,
            },
        )
        await _complete_governed_denial_idempotency(
            idem=idem,
            idem_started=idem_started,
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
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
                "request_hash": effective_request_hash,
            },
        )
        raise ValueError("idempotency_key_required")

    if governed_call and idempotency_key and not idem_started:
        try:
            idem_begin = await _begin_governed_mcp_idempotency(
                idem=idem,
                wallet_id=wallet_id,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                endpoint=endpoint,
                logical_request_payload=effective_request_payload,
                legacy_request_payload=request_payload,
                operation_kind=execution_backend,
                wait_timeout_seconds=(
                    idempotency_wait_seconds
                    if execution_backend == "upstream_mcp"
                    else 0.0
                ),
            )
            replay = idem_begin.replay
            idem_started = True
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
                    "request_hash": effective_request_hash,
                },
            )
            raise ValueError(str(exc))
        if replay and replay.response_json:
            await _assert_governed_replay_access(
                permit_id=permit_id,
                wallet_id=wallet_id,
                tool_name=tool_name,
                key_id=auth.key_id,
            )
            await _raise_replayed_error(replay)
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
                    "request_hash": effective_request_hash,
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
                    endpoint=idempotency_endpoint,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    request_payload=effective_request_payload,
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
                    endpoint=idempotency_endpoint,
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
            request_payload=effective_request_payload,
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
                endpoint=idempotency_endpoint,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                request_payload=effective_request_payload,
                arguments=arguments,
                registered_cost=registered_cost,
                audit_event_id=audit_event.event_id,
                reason=reason,
                outcome="denied",
                status_code=403,
            )
            raise ToolPermissionDenied(reason, receipt=receipt_payload)
        raise PermissionError(policy.reason)

    approval_check = None
    if governed_call and permit_model and permit_model.requires_human_approval:
        approval_check = await _require_human_approval(
            decision=decision,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=auth.key_id,
            endpoint=endpoint,
            idempotency_endpoint=idempotency_endpoint,
            transport=transport,
            idem=idem,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=effective_request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
        )

    dispatch_service: McpDispatchAttemptService | None = (
        get_mcp_dispatch_attempt_service()
        if execution_backend == "upstream_mcp"
        else None
    )
    dispatch_attempt = None

    # Linearize authorization as late as possible. For a remote call, reserve
    # permit budget and create the recoverable prepared checkpoint in the same
    # transaction; a durable reservation can therefore never exist without an
    # attempt the reconciler knows how to compensate.
    if governed_call:
        if dispatch_service is not None:
            if idem_begin is None or permit_model is None:
                raise RuntimeError("upstream_governance_context_missing")
            try:
                (
                    permit_validation,
                    dispatch_attempt,
                ) = await dispatch_service.authorize_reserve_and_prepare(
                    idempotency_record_id=idem_begin.record_id,
                    wallet_id=wallet_id,
                    permit_id=permit_model.permit_id,
                    approval_id=(
                        approval_check.approval_id if approval_check else None
                    ),
                    key_id=auth.key_id,
                    public_tool_id=tool_name,
                    upstream_tool_name=str(service["upstream_tool_name"]),
                    upstream_origin=str(service["upstream_origin"]),
                    request_hash=idem_begin.request_hash,
                    credits_authorized=registered_cost,
                )
            except Exception as exc:
                reason = "upstream_prepare_failed"
                audit_event = await _audit_mcp_invocation(
                    decision=decision,
                    endpoint=endpoint,
                    transport=transport,
                    ok=False,
                    error=reason,
                    extra_metadata={
                        **policy_metadata,
                        **_trust_metadata(
                            permit_id=permit_id,
                            idempotency_key=idempotency_key,
                            request_payload=effective_request_payload,
                            arguments=arguments,
                        ),
                        **_approval_metadata(approval_check),
                    },
                )
                receipt_payload = await _finalize_governed_denial(
                    idem=idem,
                    permit_model=permit_model,
                    wallet_id=wallet_id,
                    key_id=auth.key_id,
                    endpoint=idempotency_endpoint,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    request_payload=effective_request_payload,
                    arguments=arguments,
                    registered_cost=registered_cost,
                    audit_event_id=audit_event.event_id,
                    reason=reason,
                    outcome="failed_refunded",
                    status_code=502,
                    idempotency_record_id=idem_begin.record_id,
                    approval_id=(
                        approval_check.approval_id if approval_check else None
                    ),
                )
                raise GovernedToolError(
                    reason,
                    receipt=receipt_payload,
                    status_code=502,
                    jsonrpc_code=-32006,
                ) from exc
        else:
            permit_validation = await get_permit_service().authorize_and_reserve(
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
                    "request_hash": effective_request_hash,
                    **_approval_metadata(approval_check),
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
                    endpoint=idempotency_endpoint,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    request_payload=effective_request_payload,
                    arguments=arguments,
                    registered_cost=registered_cost,
                    audit_event_id=audit_event.event_id,
                    reason=reason,
                    outcome="denied",
                    status_code=403,
                    approval_id=(
                        approval_check.approval_id if approval_check else None
                    ),
                )
            elif permit_validation.reason:
                await _complete_governed_denial_idempotency(
                    idem=idem,
                    idem_started=idem_started,
                    wallet_id=wallet_id,
                    endpoint=idempotency_endpoint,
                    idempotency_key=idempotency_key,
                    reason=permit_validation.reason,
                )
            raise ToolPermissionDenied(reason, receipt=receipt_payload)

    description = f"MCP {transport} invoke {tool_name}"
    try:
        (
            charge_result,
            credits_charged,
            dispatch_attempt,
        ) = await _charge_and_checkpoint(
            money=money,
            idem=idem,
            dispatch_service=dispatch_service,
            dispatch_attempt=dispatch_attempt,
            governed_call=governed_call,
            wallet_id=wallet_id,
            category=category,
            charge_units=charge_units,
            request_path=endpoint,
            description=description,
            idempotency_endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            idempotency_record_id=(
                idem_begin.record_id if governed_call and idem_begin else None
            ),
            registered_cost=registered_cost,
            tool_name=tool_name,
        )
    except Exception as exc:
        if dispatch_attempt is None or idem_begin is None or not idempotency_key:
            raise
        try:
            await get_mcp_dispatch_reconciliation_service().reconcile_attempt(
                dispatch_attempt.attempt_id,
                prepared_error_code="upstream_pre_dispatch_failed",
            )
            replayed = await idem.begin_with_record(
                wallet_id=wallet_id,
                endpoint=idempotency_endpoint,
                idempotency_key=idempotency_key,
                request_payload=effective_request_payload,
                operation_kind="upstream_mcp",
            )
        except Exception:
            logger.exception(
                "mcp_upstream_pre_dispatch_reconciliation_failed",
                extra={"dispatch_attempt_id": dispatch_attempt.attempt_id},
            )
            raise exc
        if replayed.replay is not None and replayed.replay.response_json is not None:
            await _raise_replayed_error(replayed.replay)
            return replayed.replay.response_json
        raise exc
    if isinstance(charge_result, InsufficientFundsResponse):
        if dispatch_service is not None and dispatch_attempt is not None:
            dispatch_attempt = await dispatch_service.complete(
                attempt_id=dispatch_attempt.attempt_id,
                state="returned_error",
                result_payload={"error": "insufficient_funds"},
                error_code="insufficient_funds",
                max_result_bytes=settings.MCP_UPSTREAM_MAX_RESPONSE_BYTES,
            )
            await get_permit_service().release_dispatch_budget_once(
                dispatch_attempt.attempt_id
            )
        elif governed_call and permit_model:
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
            dispatch_attempt=dispatch_attempt,
            extra_metadata={
                **policy_metadata,
                **_trust_metadata(
                    permit_id=permit_id,
                    idempotency_key=idempotency_key,
                    request_payload=effective_request_payload,
                    arguments=arguments,
                ),
                **_dispatch_audit_metadata(dispatch_attempt),
                **_approval_metadata(approval_check),
            },
        )
        if governed_call and permit_model:
            receipt_outcome = (
                "failed_refunded"
                if dispatch_attempt is not None
                else "insufficient_funds"
            )
            receipt_payload = await _finalize_governed_denial(
                idem=idem,
                permit_model=permit_model,
                wallet_id=wallet_id,
                key_id=auth.key_id,
                endpoint=idempotency_endpoint,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                request_payload=effective_request_payload,
                arguments=arguments,
                registered_cost=registered_cost,
                audit_event_id=audit_event.event_id,
                reason="insufficient_funds",
                outcome=receipt_outcome,
                status_code=402,
                idempotency_record_id=(
                    idem_begin.record_id if idem_begin is not None else None
                ),
                dispatch_attempt_id=(
                    dispatch_attempt.attempt_id
                    if dispatch_attempt is not None
                    else None
                ),
                approval_id=(approval_check.approval_id if approval_check else None),
            )
            raise GovernedToolError(
                "insufficient_funds",
                receipt=receipt_payload,
                status_code=402,
                jsonrpc_code=-32004,
            )
        raise ValueError("insufficient_funds")

    # money.charge() is only ever invoked here without dry_run=True, so a real
    # (non-simulated) LedgerEntry is the only non-error outcome; this also
    # narrows the type for the ledger_entry_id/entry_id accesses below.
    assert isinstance(charge_result, LedgerEntry), (
        f"Expected LedgerEntry from non-dry-run charge, got {type(charge_result).__name__}"
    )
    assert credits_charged is not None

    if execution_backend == "upstream_mcp":
        assert upstream_executor is not None
        assert dispatch_service is not None
        assert dispatch_attempt is not None
        assert permit_model is not None
        assert idem_begin is not None
        assert idempotency_key is not None
        return await _execute_upstream_after_charge(
            executor=upstream_executor,
            dispatch_service=dispatch_service,
            dispatch_attempt=dispatch_attempt,
            decision=decision,
            money=money,
            idem=idem,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=auth.key_id,
            endpoint=endpoint,
            idempotency_endpoint=idempotency_endpoint,
            transport=transport,
            idempotency_key=idempotency_key,
            idempotency_record_id=idem_begin.record_id,
            tool_name=tool_name,
            request_payload=effective_request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            credits_charged=credits_charged,
            ledger_entry_id=charge_result.entry_id,
            description=description,
            policy_metadata=policy_metadata,
            approval_check=approval_check,
        )

    assert func is not None
    try:
        if inspect.iscoroutinefunction(func):
            result = await func(**arguments)
        else:
            result = func(**arguments)
    except Exception as exc:
        try:
            await money.refund_charge(
                wallet_id=wallet_id,
                charge_entry_id=charge_result.entry_id,
                description=f"Refund {description}",
            )
        except Exception as refund_exc:
            error = f"refund_failed:{refund_exc}; tool_error:{exc}"
            logger.error(
                "Failed to refund MCP charge %s after tool error: %s",
                charge_result.entry_id,
                refund_exc,
            )
            audit_event = None
            try:
                audit_event = await _audit_mcp_invocation(
                    decision=decision,
                    endpoint=endpoint,
                    transport=transport,
                    ok=False,
                    error=error,
                    extra_metadata={
                        **policy_metadata,
                        **_trust_metadata(
                            permit_id=permit_id,
                            idempotency_key=idempotency_key,
                            request_payload=effective_request_payload,
                            arguments=arguments,
                            ledger_entry_id=charge_result.entry_id,
                        ),
                        "refund_reconciliation_status": "pending",
                        **_approval_metadata(approval_check),
                    },
                )
            except Exception as audit_exc:
                error = f"{error}; audit_failed:{audit_exc}"
                logger.error(
                    "Failed to audit MCP refund failure for charge %s: %s",
                    charge_result.entry_id,
                    audit_exc,
                )
            if governed_call and permit_model and idempotency_key:
                receipt_payload, reconciliation = await _finalize_unrefunded_failure(
                    permit_model=permit_model,
                    wallet_id=wallet_id,
                    key_id=auth.key_id,
                    endpoint=idempotency_endpoint,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    request_payload=effective_request_payload,
                    arguments=arguments,
                    registered_cost=registered_cost,
                    credits_charged=credits_charged,
                    audit_event_id=(
                        audit_event.event_id if audit_event is not None else None
                    ),
                    ledger_entry_id=charge_result.entry_id,
                    reason=error,
                    approval_id=(
                        approval_check.approval_id if approval_check else None
                    ),
                )
                try:
                    await record_audit_event(
                        event="mcp.refund_reconciliation.pending",
                        wallet_id=wallet_id,
                        tool=tool_name,
                        endpoint=endpoint,
                        auth_source=decision.auth_source,
                        key_id=decision.key_id,
                        policy_decision_id=decision.decision_id,
                        request_id=decision.request_id,
                        ok=False,
                        error="refund_failed",
                        metadata={
                            "receipt_id": receipt_payload["receipt_id"],
                            "permit_id": permit_model.permit_id,
                            "ledger_entry_id": charge_result.entry_id,
                            "credits": str(credits_charged),
                            "status": "pending",
                            **_approval_metadata(approval_check),
                        },
                    )
                except Exception as audit_exc:
                    logger.error(
                        "Failed to audit pending MCP refund reconciliation for %s: %s",
                        charge_result.entry_id,
                        audit_exc,
                    )
                raise GovernedToolError(
                    error,
                    receipt=receipt_payload,
                    extra_data={"refund_reconciliation": reconciliation},
                    status_code=500,
                    jsonrpc_code=-32603,
                ) from refund_exc
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
                    request_payload=effective_request_payload,
                    arguments=arguments,
                    ledger_entry_id=charge_result.entry_id,
                ),
                **_approval_metadata(approval_check),
            },
        )
        if governed_call and permit_model:
            receipt_payload = await _finalize_governed_denial(
                idem=idem,
                permit_model=permit_model,
                wallet_id=wallet_id,
                key_id=auth.key_id,
                endpoint=idempotency_endpoint,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                request_payload=effective_request_payload,
                arguments=arguments,
                registered_cost=registered_cost,
                audit_event_id=audit_event.event_id,
                reason=str(exc),
                outcome="failed_refunded",
                status_code=500,
                ledger_entry_id=charge_result.entry_id,
                approval_id=(approval_check.approval_id if approval_check else None),
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

    # Finalization (audit write, receipt, idempotency-complete) is retried as
    # a unit on transient failure -- the wallet was already charged above (and
    # checkpointed via mark_charged for governed calls), so a crash here must
    # not silently report success without ever finishing these writes. Each
    # step only runs once it hasn't already succeeded in an earlier attempt,
    # so a retry can't create a duplicate audit event or receipt for the same
    # tool call. If all attempts are exhausted the original exception
    # propagates (never silently swallowed); reconcile_stuck_records is the
    # repair path for a governed record left stuck after that.
    finalize_attempts = 3
    audit_event = None
    receipt = None
    last_exc: Exception | None = None
    for attempt in range(1, finalize_attempts + 1):
        try:
            if audit_event is None:
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
                            request_payload=effective_request_payload,
                            arguments=arguments,
                            ledger_entry_id=charge_result.entry_id,
                        ),
                        **_approval_metadata(approval_check),
                    },
                )
            if governed_call and permit_model:
                if receipt is None:
                    receipt = await get_receipt_service().create_receipt(
                        permit_id=permit_model.permit_id,
                        wallet_id=wallet_id,
                        key_id=auth.key_id,
                        tool=tool_name,
                        request_payload=effective_request_payload,
                        response_payload=response_payload,
                        ledger_entry_id=charge_result.entry_id,
                        credits_authorized=registered_cost,
                        credits_charged=credits_charged,
                        outcome="success",
                        audit_event_id=audit_event.event_id,
                        idempotency_record_id=(
                            idem_begin.record_id if idem_begin is not None else None
                        ),
                        approval_id=(
                            approval_check.approval_id if approval_check else None
                        ),
                    )
                    response_payload["receipt"] = _receipt_response_payload(receipt)
                assert receipt is not None
                await idem.complete(
                    wallet_id=wallet_id,
                    endpoint=idempotency_endpoint,
                    idempotency_key=idempotency_key or "",
                    response_reference=receipt.receipt_id,
                    response_json=response_payload,
                    status_code=200,
                )
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt == finalize_attempts:
                break
            logger.warning(
                "mcp_finalize_retry attempt=%d/%d ledger_entry_id=%s error=%s",
                attempt,
                finalize_attempts,
                charge_result.entry_id,
                exc,
            )
            await asyncio.sleep(0.05 * attempt)
    if last_exc is not None:
        logger.error(
            "mcp_finalize_failed_after_retries ledger_entry_id=%s wallet_id=%s error=%s",
            charge_result.entry_id,
            wallet_id,
            last_exc,
        )
        raise last_exc
    return response_payload


def _dispatch_audit_metadata(attempt: Any | None) -> dict[str, Any]:
    """Return only operator-safe dispatch identity; never payloads or credentials."""
    if attempt is None:
        return {}
    return {
        "dispatch_attempt_id": attempt.attempt_id,
        "dispatch_state": attempt.state,
        "upstream_tool_name": attempt.upstream_tool_name,
        "upstream_origin": attempt.upstream_origin,
        "dispatch_response_hash": attempt.response_hash,
    }


def _dispatch_response_metadata(attempt: Any) -> dict[str, Any]:
    return {
        "attempt_id": attempt.attempt_id,
        "state": attempt.state,
    }


async def _charge_and_checkpoint(
    *,
    money: AgentMoney,
    idem: Any,
    dispatch_service: McpDispatchAttemptService | None,
    dispatch_attempt: Any | None,
    governed_call: bool,
    wallet_id: str,
    category: ServiceCategory,
    charge_units: Decimal,
    request_path: str,
    description: str,
    idempotency_endpoint: str,
    idempotency_key: str | None,
    idempotency_record_id: str | None,
    registered_cost: Decimal,
    tool_name: str,
) -> tuple[LedgerEntry | InsufficientFundsResponse, Decimal | None, Any | None]:
    """Debit and durably link every pre-dispatch checkpoint.

    Any exception is handled by the caller through targeted reconciliation,
    which inspects the operation-keyed debit even when commit acknowledgement
    was lost. This helper never writes an unsigned terminal idempotency result.
    """
    charge_result = await money.charge(
        wallet_id=wallet_id,
        service_category=category,
        units=charge_units,
        request_path=request_path,
        description=description,
        operation_key=idempotency_record_id if governed_call else None,
    )
    if isinstance(charge_result, InsufficientFundsResponse):
        return charge_result, None, dispatch_attempt
    if not isinstance(charge_result, LedgerEntry):
        raise RuntimeError("governed_charge_result_invalid")

    if governed_call and idempotency_key:
        await idem.mark_charged(
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            ledger_entry_id=charge_result.entry_id,
        )

    from app.services.governed_metering import aligned_credits_charged

    credits_charged = aligned_credits_charged(
        ledger_amount=charge_result.amount,
        authorized_credits=registered_cost,
        context=f"mcp:{tool_name}",
    )
    if dispatch_service is not None and dispatch_attempt is not None:
        dispatch_attempt = await dispatch_service.attach_charge(
            attempt_id=dispatch_attempt.attempt_id,
            ledger_entry_id=charge_result.entry_id,
            credits_charged=credits_charged,
        )
    return charge_result, credits_charged, dispatch_attempt


async def _execute_upstream_after_charge(
    *,
    executor: Any,
    dispatch_service: McpDispatchAttemptService,
    dispatch_attempt: Any,
    decision: PolicyDecision,
    money: AgentMoney,
    idem: Any,
    permit_model: Any,
    wallet_id: str,
    key_id: str | None,
    endpoint: str,
    idempotency_endpoint: str,
    transport: str,
    idempotency_key: str,
    idempotency_record_id: str,
    tool_name: str,
    request_payload: dict[str, Any],
    arguments: dict[str, Any],
    registered_cost: Decimal,
    credits_charged: Decimal,
    ledger_entry_id: str,
    description: str,
    policy_metadata: dict[str, Any],
    approval_check: Any | None,
) -> dict[str, Any]:
    """Dispatch once and durably classify every post-charge remote outcome."""

    async def mark_dispatched() -> None:
        await dispatch_service.mark_dispatched(dispatch_attempt.attempt_id)

    async def raise_response_rejected(
        error_code: str,
        *,
        persist_terminal_payload: bool = True,
    ) -> None:
        terminal_payload = {
            "error": "response_rejected",
            "error_code": error_code,
        }
        terminal = await dispatch_service.complete(
            attempt_id=dispatch_attempt.attempt_id,
            state="response_rejected",
            result_payload=(terminal_payload if persist_terminal_payload else None),
            error_code=error_code,
            max_result_bytes=settings.MCP_UPSTREAM_MAX_RESPONSE_BYTES,
        )
        await _raise_charged_upstream_failure(
            reason="response_rejected",
            outcome="response_rejected",
            status_code=502,
            jsonrpc_code=-32006,
            terminal_payload=terminal_payload,
            dispatch_attempt=terminal,
            decision=decision,
            idem=idem,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=key_id,
            endpoint=endpoint,
            idempotency_endpoint=idempotency_endpoint,
            transport=transport,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            credits_charged=credits_charged,
            ledger_entry_id=ledger_entry_id,
            policy_metadata=policy_metadata,
            approval_check=approval_check,
        )
        raise AssertionError("unreachable")

    def persistence_rejection_code(exc: DispatchResultRejectedError) -> str:
        if isinstance(exc, DispatchResultTooLargeError):
            return "upstream_response_too_large"
        return "upstream_response_invalid"

    try:
        upstream_result = await executor.call_tool(
            arguments,
            invocation_id=idempotency_record_id,
            idempotency_key=idempotency_key,
            before_dispatch=mark_dispatched,
        )
    except UpstreamMcpReturnedError as exc:
        try:
            terminal = await dispatch_service.complete(
                attempt_id=dispatch_attempt.attempt_id,
                state="returned_error",
                result_payload=exc.result.payload,
                error_code="upstream_returned_error",
                max_result_bytes=settings.MCP_UPSTREAM_MAX_RESPONSE_BYTES,
            )
        except DispatchResultRejectedError as persistence_error:
            await raise_response_rejected(
                persistence_rejection_code(persistence_error),
                persist_terminal_payload=False,
            )
            raise AssertionError("unreachable")
        await _raise_refunded_upstream_failure(
            reason="upstream_returned_error",
            terminal_payload=exc.result.payload,
            dispatch_attempt=terminal,
            dispatch_service=dispatch_service,
            decision=decision,
            money=money,
            idem=idem,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=key_id,
            endpoint=endpoint,
            idempotency_endpoint=idempotency_endpoint,
            transport=transport,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            credits_charged=credits_charged,
            ledger_entry_id=ledger_entry_id,
            description=description,
            policy_metadata=policy_metadata,
            approval_check=approval_check,
        )
        raise AssertionError("unreachable")
    except UpstreamMcpPreDispatchError as exc:
        terminal_payload = {
            "error": "failed_refunded",
            "error_code": exc.code,
        }
        terminal = await dispatch_service.complete(
            attempt_id=dispatch_attempt.attempt_id,
            state="returned_error",
            result_payload=terminal_payload,
            error_code=exc.code,
            max_result_bytes=settings.MCP_UPSTREAM_MAX_RESPONSE_BYTES,
        )
        await _raise_refunded_upstream_failure(
            reason="upstream_pre_dispatch_failed",
            terminal_payload=terminal_payload,
            dispatch_attempt=terminal,
            dispatch_service=dispatch_service,
            decision=decision,
            money=money,
            idem=idem,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=key_id,
            endpoint=endpoint,
            idempotency_endpoint=idempotency_endpoint,
            transport=transport,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            credits_charged=credits_charged,
            ledger_entry_id=ledger_entry_id,
            description=description,
            policy_metadata=policy_metadata,
            approval_check=approval_check,
        )
        raise AssertionError("unreachable")
    except UpstreamMcpDeliveryUncertainError:
        terminal_payload = {"error": "delivery_uncertain"}
        terminal = await dispatch_service.complete(
            attempt_id=dispatch_attempt.attempt_id,
            state="delivery_uncertain",
            result_payload=terminal_payload,
            error_code="delivery_uncertain",
            max_result_bytes=settings.MCP_UPSTREAM_MAX_RESPONSE_BYTES,
        )
        logger.warning(
            "mcp_upstream_delivery_uncertain",
            extra={
                "dispatch_attempt_id": terminal.attempt_id,
                "public_tool_id": terminal.public_tool_id,
                "upstream_origin": terminal.upstream_origin,
            },
        )
        await _raise_charged_upstream_failure(
            reason="delivery_uncertain",
            outcome="delivery_uncertain",
            status_code=504,
            jsonrpc_code=-32005,
            terminal_payload=terminal_payload,
            dispatch_attempt=terminal,
            decision=decision,
            idem=idem,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=key_id,
            endpoint=endpoint,
            idempotency_endpoint=idempotency_endpoint,
            transport=transport,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            credits_charged=credits_charged,
            ledger_entry_id=ledger_entry_id,
            policy_metadata=policy_metadata,
            approval_check=approval_check,
        )
        raise AssertionError("unreachable")
    except UpstreamMcpResponseRejectedError as exc:
        await raise_response_rejected(exc.code)
        raise AssertionError("unreachable")

    try:
        terminal = await dispatch_service.complete(
            attempt_id=dispatch_attempt.attempt_id,
            state="succeeded",
            result_payload=upstream_result.payload,
            error_code=None,
            max_result_bytes=settings.MCP_UPSTREAM_MAX_RESPONSE_BYTES,
        )
    except DispatchResultRejectedError as persistence_error:
        await raise_response_rejected(
            persistence_rejection_code(persistence_error),
            persist_terminal_payload=False,
        )
        raise AssertionError("unreachable")
    audit_event = await _audit_mcp_invocation(
        decision=decision,
        endpoint=endpoint,
        transport=transport,
        ok=True,
        error=None,
        dispatch_attempt=terminal,
        extra_metadata={
            **policy_metadata,
            **_trust_metadata(
                permit_id=permit_model.permit_id,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                arguments=arguments,
                ledger_entry_id=ledger_entry_id,
            ),
            **_dispatch_audit_metadata(terminal),
            **_approval_metadata(approval_check),
        },
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit_model.permit_id,
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool_name,
        request_payload=request_payload,
        response_payload=upstream_result.payload,
        ledger_entry_id=ledger_entry_id,
        credits_authorized=registered_cost,
        credits_charged=credits_charged,
        outcome="success",
        audit_event_id=audit_event.event_id,
        idempotency_record_id=idempotency_record_id,
        dispatch_attempt_id=terminal.attempt_id,
        response_hash_override=terminal.response_hash,
        approval_id=(approval_check.approval_id if approval_check else None),
    )
    response_payload = dict(upstream_result.payload)
    response_payload["receipt"] = _receipt_response_payload(receipt)
    await idem.complete(
        wallet_id=wallet_id,
        endpoint=idempotency_endpoint,
        idempotency_key=idempotency_key,
        response_reference=receipt.receipt_id,
        response_json=response_payload,
        status_code=200,
    )
    return response_payload


async def _raise_refunded_upstream_failure(
    *,
    reason: str,
    terminal_payload: dict[str, Any],
    dispatch_attempt: Any,
    dispatch_service: McpDispatchAttemptService,
    decision: PolicyDecision,
    money: AgentMoney,
    idem: Any,
    permit_model: Any,
    wallet_id: str,
    key_id: str | None,
    endpoint: str,
    idempotency_endpoint: str,
    transport: str,
    idempotency_key: str,
    tool_name: str,
    request_payload: dict[str, Any],
    arguments: dict[str, Any],
    registered_cost: Decimal,
    credits_charged: Decimal,
    ledger_entry_id: str,
    description: str,
    policy_metadata: dict[str, Any],
    approval_check: Any | None,
) -> None:
    """Compensate a confirmed failure and sign its terminal evidence."""
    try:
        await money.refund_charge(
            wallet_id=wallet_id,
            charge_entry_id=ledger_entry_id,
            description=f"Refund {description}",
        )
        await dispatch_service.mark_debit_refunded(
            attempt_id=dispatch_attempt.attempt_id,
            ledger_entry_id=ledger_entry_id,
        )
    except Exception as refund_exc:
        error = f"refund_failed; upstream_error:{reason}"
        audit_event = await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=error,
            dispatch_attempt=dispatch_attempt,
            extra_metadata={
                **policy_metadata,
                **_trust_metadata(
                    permit_id=permit_model.permit_id,
                    idempotency_key=idempotency_key,
                    request_payload=request_payload,
                    arguments=arguments,
                    ledger_entry_id=ledger_entry_id,
                ),
                **_dispatch_audit_metadata(dispatch_attempt),
                "refund_reconciliation_status": "pending",
                **_approval_metadata(approval_check),
            },
        )
        receipt_payload, reconciliation = await _finalize_unrefunded_failure(
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=key_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            credits_charged=credits_charged,
            audit_event_id=audit_event.event_id,
            ledger_entry_id=ledger_entry_id,
            reason=error,
            dispatch_attempt_id=dispatch_attempt.attempt_id,
            response_payload=terminal_payload,
            response_hash_override=dispatch_attempt.response_hash,
            approval_id=(approval_check.approval_id if approval_check else None),
        )
        raise GovernedToolError(
            error,
            receipt=receipt_payload,
            extra_data={"refund_reconciliation": reconciliation},
            status_code=500,
            jsonrpc_code=-32603,
        ) from refund_exc

    await get_permit_service().release_dispatch_budget_once(dispatch_attempt.attempt_id)
    audit_event = await _audit_mcp_invocation(
        decision=decision,
        endpoint=endpoint,
        transport=transport,
        ok=False,
        error=reason,
        dispatch_attempt=dispatch_attempt,
        extra_metadata={
            **policy_metadata,
            **_trust_metadata(
                permit_id=permit_model.permit_id,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                arguments=arguments,
                ledger_entry_id=ledger_entry_id,
            ),
            **_dispatch_audit_metadata(dispatch_attempt),
            **_approval_metadata(approval_check),
        },
    )
    response_extra_data = {
        "upstream_result": terminal_payload,
        "dispatch": _dispatch_response_metadata(dispatch_attempt),
    }
    receipt_payload = await _finalize_governed_denial(
        idem=idem,
        permit_model=permit_model,
        wallet_id=wallet_id,
        key_id=key_id,
        endpoint=idempotency_endpoint,
        idempotency_key=idempotency_key,
        tool_name=tool_name,
        request_payload=request_payload,
        arguments=arguments,
        registered_cost=registered_cost,
        audit_event_id=audit_event.event_id,
        reason=reason,
        outcome="failed_refunded",
        status_code=502,
        ledger_entry_id=ledger_entry_id,
        idempotency_record_id=dispatch_attempt.idempotency_record_id,
        dispatch_attempt_id=dispatch_attempt.attempt_id,
        response_payload=terminal_payload,
        response_hash_override=dispatch_attempt.response_hash,
        response_extra_data=response_extra_data,
        approval_id=(approval_check.approval_id if approval_check else None),
    )
    raise GovernedToolError(
        reason,
        receipt=receipt_payload,
        extra_data=response_extra_data,
        status_code=502,
        jsonrpc_code=-32006,
    )


async def _raise_charged_upstream_failure(
    *,
    reason: str,
    outcome: str,
    status_code: int,
    jsonrpc_code: int,
    terminal_payload: dict[str, Any],
    dispatch_attempt: Any,
    decision: PolicyDecision,
    idem: Any,
    permit_model: Any,
    wallet_id: str,
    key_id: str | None,
    endpoint: str,
    idempotency_endpoint: str,
    transport: str,
    idempotency_key: str,
    tool_name: str,
    request_payload: dict[str, Any],
    arguments: dict[str, Any],
    registered_cost: Decimal,
    credits_charged: Decimal,
    ledger_entry_id: str,
    policy_metadata: dict[str, Any],
    approval_check: Any | None,
) -> None:
    """Sign an ambiguous/rejected response without refunding or releasing budget."""
    audit_event = await _audit_mcp_invocation(
        decision=decision,
        endpoint=endpoint,
        transport=transport,
        ok=False,
        error=reason,
        dispatch_attempt=dispatch_attempt,
        extra_metadata={
            **policy_metadata,
            **_trust_metadata(
                permit_id=permit_model.permit_id,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                arguments=arguments,
                ledger_entry_id=ledger_entry_id,
            ),
            **_dispatch_audit_metadata(dispatch_attempt),
            **_approval_metadata(approval_check),
        },
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit_model.permit_id,
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool_name,
        request_payload=request_payload,
        response_payload=(
            terminal_payload if dispatch_attempt.response_hash is not None else None
        ),
        response_hash_override=dispatch_attempt.response_hash,
        ledger_entry_id=ledger_entry_id,
        credits_authorized=registered_cost,
        credits_charged=credits_charged,
        outcome=outcome,
        audit_event_id=audit_event.event_id,
        idempotency_record_id=dispatch_attempt.idempotency_record_id,
        dispatch_attempt_id=dispatch_attempt.attempt_id,
        approval_id=(approval_check.approval_id if approval_check else None),
    )
    receipt_payload = _receipt_response_payload(receipt)
    response_extra_data = {"dispatch": _dispatch_response_metadata(dispatch_attempt)}
    await idem.complete(
        wallet_id=wallet_id,
        endpoint=idempotency_endpoint,
        idempotency_key=idempotency_key,
        response_reference=receipt.receipt_id,
        response_json=_governed_error_payload(
            reason,
            receipt_payload,
            extra_data=response_extra_data,
        ),
        status_code=status_code,
    )
    raise GovernedToolError(
        reason,
        receipt=receipt_payload,
        extra_data=response_extra_data,
        status_code=status_code,
        jsonrpc_code=jsonrpc_code,
    )


def _registered_tool_cost(
    service: dict[str, Any],
    category: ServiceCategory,
) -> Decimal:
    default_price = DEFAULT_PRICING[category][1]
    exact_price = service.get("credits_per_unit_exact")
    if exact_price is not None:
        return Decimal(str(exact_price))
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
    *,
    extra_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "content": [],
        "isError": True,
        "error": reason,
        "receipt": receipt,
    }
    payload.update(extra_data or {})
    return payload


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
    idempotency_record_id: str | None = None,
    dispatch_attempt_id: str | None = None,
    response_payload: dict[str, Any] | None = None,
    response_hash_override: str | None = None,
    response_extra_data: dict[str, Any] | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Sign a non-success governed receipt and record the idempotent outcome.

    Shared by every governed terminal-failure branch (permit denied, policy
    denied, insufficient funds, tool execution failure) so the receipt contract
    and idempotency completion are written in exactly one place.
    """
    if idempotency_record_id is None and idempotency_key:
        record = await idem.get_record(
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
        )
        idempotency_record_id = record.record_id if record is not None else None
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit_model.permit_id,
        wallet_id=wallet_id,
        key_id=key_id,
        tool=tool_name,
        request_payload=request_payload or arguments,
        response_payload=response_payload or {"error": reason},
        ledger_entry_id=ledger_entry_id,
        credits_authorized=registered_cost,
        credits_charged=Decimal("0"),
        outcome=outcome,
        audit_event_id=audit_event_id,
        idempotency_record_id=idempotency_record_id,
        dispatch_attempt_id=dispatch_attempt_id,
        response_hash_override=response_hash_override,
        approval_id=approval_id,
    )
    receipt_payload = _receipt_response_payload(receipt)
    await idem.complete(
        wallet_id=wallet_id,
        endpoint=endpoint,
        idempotency_key=idempotency_key or "",
        response_reference=receipt.receipt_id,
        response_json=_governed_error_payload(
            reason,
            receipt_payload,
            extra_data=response_extra_data,
        ),
        status_code=status_code,
    )
    return receipt_payload


async def _finalize_unrefunded_failure(
    *,
    permit_model: Any,
    wallet_id: str,
    key_id: str | None,
    endpoint: str,
    idempotency_key: str,
    tool_name: str,
    request_payload: dict[str, Any] | None,
    arguments: dict[str, Any],
    registered_cost: Decimal,
    credits_charged: Decimal,
    audit_event_id: str | None,
    ledger_entry_id: str,
    reason: str,
    dispatch_attempt_id: str | None = None,
    response_payload: dict[str, Any] | None = None,
    response_hash_override: str | None = None,
    approval_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist the signed failure and its exact-once operator work item."""
    receipt, reconciliation = await get_refund_reconciliation_service().create_pending(
        wallet_id=wallet_id,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        permit_id=permit_model.permit_id,
        key_id=key_id,
        tool_name=tool_name,
        request_payload=request_payload or arguments,
        ledger_entry_id=ledger_entry_id,
        credits_authorized=registered_cost,
        credits_charged=credits_charged,
        audit_event_id=audit_event_id,
        reason=reason,
        dispatch_attempt_id=dispatch_attempt_id,
        response_payload=response_payload,
        response_hash_override=response_hash_override,
        approval_id=approval_id,
    )
    receipt_payload = _receipt_response_payload(receipt)
    return receipt_payload, reconciliation


async def _assert_governed_replay_access(
    *,
    permit_id: str | None,
    wallet_id: str,
    tool_name: str,
    key_id: str | None,
) -> None:
    """Keep terminal replay bound to the permit's stable caller identity."""
    validation = await get_permit_service().validate_replay_access(
        permit_id=permit_id or "",
        wallet_id=wallet_id,
        tool_name=tool_name,
        key_id=key_id,
    )
    if not validation.allowed:
        raise ToolPermissionDenied(validation.reason or "permit_denied")


def _approval_metadata(approval_check: Any) -> dict[str, Any]:
    """Audit-metadata fragment for the human-approval gate (signed via chain)."""
    if approval_check is None:
        return {}
    metadata: dict[str, Any] = {
        "approval_id": approval_check.approval_id,
        "approval_status": approval_check.status,
    }
    if approval_check.sentinel_action_id:
        metadata["sentinel_action_id"] = approval_check.sentinel_action_id
    if approval_check.simulated:
        metadata["approval_simulated"] = True
    return metadata


async def _require_human_approval(
    *,
    decision: PolicyDecision,
    permit_model: Any,
    wallet_id: str,
    key_id: str | None,
    endpoint: str,
    idempotency_endpoint: str,
    transport: str,
    idem: Any,
    idempotency_key: str | None,
    tool_name: str,
    request_payload: dict[str, Any] | None,
    arguments: dict[str, Any],
    registered_cost: Decimal,
) -> Any:
    """Enforce the permit's human-approval gate before any budget moves.

    Returns the approved ``ApprovalCheck`` or raises:

    - ``HumanApprovalPendingSignal`` (decision pending / Sentinel unreachable):
      retryable — the idempotency record is abandoned so the same key can be
      retried, and no receipt is written because nothing terminal happened.
    - ``ToolPermissionDenied`` (rejected / expired / misconfigured): terminal —
      a denied receipt is signed and the idempotency record completes, so
      replays of this key return the same denial.
    """
    trust_metadata = _trust_metadata(
        permit_id=permit_model.permit_id,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        arguments=arguments,
    )

    async def _terminal_denial(reason: str, approval_id: str | None) -> NoReturn:
        audit_event = await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=reason,
            extra_metadata=trust_metadata,
        )
        receipt_payload = await _finalize_governed_denial(
            idem=idem,
            permit_model=permit_model,
            wallet_id=wallet_id,
            key_id=key_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            request_payload=request_payload,
            arguments=arguments,
            registered_cost=registered_cost,
            audit_event_id=audit_event.event_id,
            reason=reason,
            outcome="denied",
            status_code=403,
            approval_id=approval_id,
        )
        raise ToolPermissionDenied(reason, receipt=receipt_payload)

    async def _retryable(
        reason: str, *, data: dict[str, Any], status_code: int
    ) -> NoReturn:
        await _audit_mcp_invocation(
            decision=decision,
            endpoint=endpoint,
            transport=transport,
            ok=False,
            error=reason,
            extra_metadata={**trust_metadata, **data},
        )
        # Nothing was charged and no terminal outcome exists: free the key so
        # the same invoke can be retried once the condition clears.
        await idem.abandon(
            wallet_id=wallet_id,
            endpoint=idempotency_endpoint,
            idempotency_key=idempotency_key or "",
        )
        raise HumanApprovalPendingSignal(reason, data=data, status_code=status_code)

    try:
        approval_check = await get_human_approval_service().ensure_approval(
            wallet_id=wallet_id,
            permit_id=permit_model.permit_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key or "",
            arguments=arguments,
            estimated_credits=registered_cost,
        )
    except HumanApprovalUnavailableError as exc:
        await _retryable(exc.reason, data={}, status_code=503)
    except HumanApprovalError as exc:
        await _terminal_denial(exc.reason, None)
    except Exception:
        # Never let an unexpected error strand the caller's in-progress
        # idempotency record (reconcile can't repair an uncharged one). Fail
        # closed and retryable: release the key, execute nothing, surface an
        # outage. Logged loudly so it isn't silently swallowed.
        logger.exception("human_approval_gate_unexpected_error")
        await _retryable("human_approval_unavailable", data={}, status_code=503)

    approval_data = _approval_metadata(approval_check)
    if approval_check.status == APPROVAL_STATUS_PENDING:
        await _retryable(
            "human_approval_pending",
            data={
                **approval_data,
                "expires_at": approval_check.expires_at.isoformat(),
            },
            status_code=202,
        )
    if approval_check.status != APPROVAL_STATUS_APPROVED:
        # rejected or expired
        await _terminal_denial(
            f"human_approval_{approval_check.status}", approval_check.approval_id
        )
    return approval_check


async def _raise_replayed_error(replay: Any) -> None:
    if replay.status_code < 400 or not replay.response_json:
        return
    reason = str(replay.response_json.get("error") or "governed_call_failed")
    receipt = replay.response_json.get("receipt")
    extra_data = {}
    reconciliation = replay.response_json.get("refund_reconciliation")
    if isinstance(reconciliation, dict):
        if reconciliation.get("status") == "resolved":
            try:
                receipt_id = replay.response_reference
                if (
                    not isinstance(receipt_id, str)
                    or reconciliation.get("receipt_id") != receipt_id
                ):
                    raise ValueError("resolved_replay_linkage_invalid")
                validated = (
                    await get_refund_reconciliation_service().validate_resolved_claim(
                        receipt_id=receipt_id
                    )
                )
                if validated.status != "resolved":
                    raise ValueError("resolved_replay_state_invalid")
            except Exception as exc:
                # Do not replay the claimed resolution or its attached receipt
                # when the ledger cannot substantiate it.
                raise GovernedToolError(
                    "refund_reconciliation_resolution_invalid",
                    status_code=409,
                    jsonrpc_code=-32603,
                ) from exc
        extra_data["refund_reconciliation"] = reconciliation
    upstream_result = replay.response_json.get("upstream_result")
    if isinstance(upstream_result, dict):
        extra_data["upstream_result"] = upstream_result
    dispatch = replay.response_json.get("dispatch")
    if isinstance(dispatch, dict):
        extra_data["dispatch"] = dispatch
    if replay.status_code == 403:
        raise ToolPermissionDenied(reason, receipt=receipt)
    raise GovernedToolError(
        reason,
        receipt=receipt,
        extra_data=extra_data,
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
    if reason == "delivery_uncertain":
        return -32005
    if reason == "response_rejected":
        return -32006
    if reason in {"upstream_returned_error", "upstream_pre_dispatch_failed"}:
        return -32006
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
    dispatch_attempt: Any | None = None,
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
    if dispatch_attempt is not None:
        metadata_attempt_id = (extra_metadata or {}).get("dispatch_attempt_id")
        if metadata_attempt_id != dispatch_attempt.attempt_id:
            raise RuntimeError("dispatch_audit_identity_mismatch")
        return await get_mcp_dispatch_reconciliation_service().get_or_create_terminal_audit(
            dispatch_attempt.attempt_id
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

    This endpoint verifies the API key, applies the governed billing path, and
    executes either a registered local callable or the single configured
    upstream MCP tool. Metadata-only database service registrations are not
    executable through MCP.
    """
    mcp_context = request.mcp_context
    if not mcp_context:
        mcp_context = McpContext(
            wallet_id=request.arguments.get("wallet_id", ""),
            request_path=None,
            permit_id=None,
            idempotency_key=None,
        )

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
    except HumanApprovalPendingSignal as exc:
        detail: dict[str, Any] = {"error": str(exc)}
        if exc.data:
            detail["approval"] = exc.data
        raise HTTPException(status_code=exc.status_code, detail=detail)
    except ToolPermissionDenied as exc:
        detail = {"error": str(exc)}
        if exc.receipt:
            detail["receipt"] = exc.receipt
        raise HTTPException(status_code=403, detail=detail)
    except GovernedToolError as exc:
        detail = {"error": str(exc)}
        if exc.receipt:
            detail["receipt"] = exc.receipt
        detail.update(exc.extra_data)
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
    - output schema availability metadata
    - pricing and category annotations
    """
    _ensure_local_mcp_tools_registered()
    registry = get_service_registry()

    service = registry.get_local(service_id)

    if not service:
        raise HTTPException(
            status_code=404,
            detail=f"Executable tool not found: {service_id}",
        )

    generator = get_mcp_generator()
    tool = generator._service_to_mcp_tool(service)
    return tool
