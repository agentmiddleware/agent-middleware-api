"""Spec-compliant Streamable HTTP MCP endpoint (stateless JSON mode).

``POST /mcp`` serves the standard MCP lifecycle subset this trust plane can
honestly claim: ``initialize``, notifications, ``ping``, ``tools/list``, and
``tools/call``. It exists so standard MCP clients (Claude Code, the official
SDK clients) can connect without knowing anything about permits.

Standard clients cannot supply the wallet/permit context the governed
adapter requires, so ``tools/call`` mints a bounded, signed, single-tool,
short-lived permit on behalf of the caller's wallet (derived from its
API key) and then delegates to the same governed invoke path as
``/mcp/messages``. The full permit -> meter -> receipt -> audit loop applies
unchanged; only the minting step moves server-side. Bootstrap/admin keys
have no wallet and are refused: there is no wallet to encumber, and this
endpoint must never bypass metering.

Replay safety: a client-supplied ``Idempotency-Key`` header (or the
``io.agentmiddleware/idempotency_key`` entry in ``params._meta``) is honored
exactly like the governed endpoints. Without one, each call gets a fresh
generated key, so client retries are charged as new calls — the same
contract as an un-keyed governed invoke.

The endpoint is stateless: no ``Mcp-Session-Id`` is issued, responses are
plain JSON (never SSE), and there is no server-initiated stream, so GET and
DELETE answer 405. Disabled by default — ``ENABLE_STANDARD_MCP_ENDPOINT``
must be set explicitly, so the surface cannot be advertised (or preflighted
by the registry publish gate) before an operator turns it on.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.auth import AuthContext, get_auth_context
from app.core.config import get_settings
from app.core.time import utc_now
from app.routers.mcp import (
    GovernedToolError,
    HumanApprovalPendingSignal,
    ToolPermissionDenied,
    _handle_tools_call,
    _handle_tools_list,
    _value_error_jsonrpc_code,
)
from app.schemas.trust import PermitCreateRequest
from app.services.agent_money import AgentMoney, get_agent_money
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.mcp_generator import MCP_SERVER_VERSION, McpGenerator
from app.services.permits import PermitError, get_permit_service
from app.services.service_registry import get_service_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP Standard Endpoint"])

# Newest first: the first entry is offered when the client requests a
# version this server does not support.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_IDEMPOTENCY_META_KEY = "io.agentmiddleware/idempotency_key"
_MAX_META_VALUE_LENGTH = 256

# Idempotency scope for auto-minted permits; distinct from the governed-call
# scope so mint replay and call replay never collide.
_AUTO_PERMIT_ENDPOINT = "/mcp#auto-permit"


def _permit_error_response(request_id: Any, exc: PermitError) -> JSONResponse:
    code = -32004 if exc.reason == "permit_budget_exceeds_wallet_balance" else -32003
    return _jsonrpc_error(request_id, code, exc.reason)


def _jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error})


def _require_enabled() -> None:
    if not get_settings().ENABLE_STANDARD_MCP_ENDPOINT:
        raise HTTPException(status_code=404, detail="Not Found")


def _validate_origin(request: Request) -> None:
    """Reject cross-origin browser calls (DNS-rebinding hardening).

    Non-browser MCP clients send no Origin header and pass through.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    origin_host = urlsplit(origin).hostname
    allowed = {request.url.hostname}
    public_url = get_settings().PUBLIC_URL
    if public_url:
        allowed.add(urlsplit(public_url).hostname)
    if origin_host not in allowed:
        raise HTTPException(status_code=403, detail={"error": "origin_not_allowed"})


def _initialize_result(params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    negotiated = (
        requested
        if requested in SUPPORTED_PROTOCOL_VERSIONS
        else SUPPORTED_PROTOCOL_VERSIONS[0]
    )
    return {
        "protocolVersion": negotiated,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": McpGenerator.MANIFEST_NAME,
            "version": MCP_SERVER_VERSION,
        },
        "instructions": (
            "Governed MCP trust plane. Every tools/call is authorized by a "
            "server-minted, wallet-bounded permit, metered against the "
            "caller's credit balance, and answered with a signed receipt. "
            "Authenticate with a wallet-scoped API key; send an "
            "Idempotency-Key header to make retries replay-safe."
        ),
    }


def _meta_idempotency_key(params: dict[str, Any]) -> str | None:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    value = meta.get(_IDEMPOTENCY_META_KEY)
    if isinstance(value, str) and 0 < len(value) <= _MAX_META_VALUE_LENGTH:
        return value
    return None


def _tool_call_budget(record: dict[str, Any]) -> Decimal:
    """Bound the auto-minted permit to the tool's per-call cost.

    Permits must carry a positive budget, so a zero-cost tool is bounded at
    one credit; nothing is charged beyond the actual metered cost either way.
    """
    exact = record.get("credits_per_unit_exact")
    if exact is not None:
        try:
            cost = Decimal(str(exact))
        except InvalidOperation:
            cost = Decimal(str(record.get("credits_per_unit", 1.0)))
    else:
        cost = Decimal(str(record.get("credits_per_unit", 1.0)))
    return cost if cost > 0 else Decimal("1")


async def _standard_tools_call(
    request: Request,
    body: dict[str, Any],
    params: dict[str, Any],
    request_id: Any,
    auth: AuthContext,
    money: AgentMoney,
) -> JSONResponse:
    name = params.get("name")
    if not name or not isinstance(name, str):
        return _jsonrpc_error(request_id, -32602, "Missing tool name")

    if not auth.wallet_id:
        return _jsonrpc_error(
            request_id,
            -32003,
            "wallet_scoped_key_required: this endpoint mints permits from the "
            "caller's wallet; authenticate with a wallet-scoped API key",
        )

    record = get_service_registry().get_local(name)
    if record is None:
        return _jsonrpc_error(request_id, -32001, f"Tool not found: {name}")

    client_key = request.headers.get("Idempotency-Key") or _meta_idempotency_key(
        params
    )
    idempotency_key = client_key or f"mcp-auto-{uuid.uuid4().hex}"

    settings = get_settings()
    permit_request = PermitCreateRequest(
        issuer_wallet_id=auth.wallet_id,
        subject_wallet_id=auth.wallet_id,
        subject_key_id=auth.key_id,
        allowed_tools=[name],
        max_credits=_tool_call_budget(record),
        expires_at=utc_now()
        + timedelta(seconds=settings.STANDARD_MCP_PERMIT_TTL_SECONDS),
    )

    # The governed replay hash covers the permit id, so a retried
    # idempotency key must resolve to the SAME auto-minted permit — mint
    # through an idempotency record keyed off the client's key. Generated
    # keys are unique per call and skip this bookkeeping.
    permit_id: str | None = None
    if client_key:
        idem = get_idempotency_service()
        mint_key = (
            "smcp-" + hashlib.sha256(client_key.encode("utf-8")).hexdigest()[:48]
        )
        mint_payload = {
            "kind": "standard-mcp-auto-permit",
            "tool": name,
            "wallet_id": auth.wallet_id,
            "subject_key_id": auth.key_id,
        }
        try:
            mint_replay = await idem.begin(
                wallet_id=auth.wallet_id,
                endpoint=_AUTO_PERMIT_ENDPOINT,
                idempotency_key=mint_key,
                request_payload=mint_payload,
            )
        except IdempotencyConflictError:
            return _jsonrpc_error(request_id, -32003, "idempotency_key_reused")
        except IdempotencyInProgressError:
            return _jsonrpc_error(request_id, -32003, "idempotency_in_progress")
        if mint_replay and mint_replay.response_json:
            permit_id = mint_replay.response_json.get("permit_id")
        else:
            try:
                permit = await get_permit_service().create_permit(
                    permit_request, subject_key_id=auth.key_id
                )
            except PermitError as exc:
                await idem.abandon(
                    wallet_id=auth.wallet_id,
                    endpoint=_AUTO_PERMIT_ENDPOINT,
                    idempotency_key=mint_key,
                )
                return _permit_error_response(request_id, exc)
            await idem.complete(
                wallet_id=auth.wallet_id,
                endpoint=_AUTO_PERMIT_ENDPOINT,
                idempotency_key=mint_key,
                response_reference=permit.permit_id,
                response_json={"permit_id": permit.permit_id},
                status_code=201,
            )
            permit_id = permit.permit_id
    else:
        try:
            permit = await get_permit_service().create_permit(
                permit_request, subject_key_id=auth.key_id
            )
        except PermitError as exc:
            return _permit_error_response(request_id, exc)
        permit_id = permit.permit_id

    call_params = {
        "name": name,
        "arguments": params.get("arguments") or {},
        "mcpContext": {
            "wallet_id": auth.wallet_id,
            "permit_id": permit_id,
            "idempotency_key": idempotency_key,
        },
    }
    try:
        result = await _handle_tools_call(
            call_params,
            auth=auth,
            money=money,
            transport="jsonrpc",
            endpoint="/mcp",
            request_id=str(request_id) if request_id is not None else None,
            idempotency_key=idempotency_key,
            request_payload=body,
        )
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
    except HumanApprovalPendingSignal as e:
        return _jsonrpc_error(request_id, e.jsonrpc_code, str(e), e.data or None)
    except ToolPermissionDenied as e:
        data = {"receipt": e.receipt} if e.receipt else None
        return _jsonrpc_error(request_id, -32003, str(e), data)
    except GovernedToolError as e:
        data = dict(e.extra_data)
        if e.receipt:
            data["receipt"] = e.receipt
        return _jsonrpc_error(request_id, e.jsonrpc_code, str(e), data or None)
    except PermissionError as e:
        return _jsonrpc_error(request_id, -32003, str(e))
    except ValueError as e:
        code = _value_error_jsonrpc_code(str(e))
        if code == -32603:
            logger.error(f"Standard MCP tool call failed: {e}")
        return _jsonrpc_error(request_id, code, str(e))
    except Exception as e:
        logger.error(f"Standard MCP tool call failed: {e}")
        return _jsonrpc_error(request_id, -32603, str(e))


@router.post(
    "",
    name="MCP Streamable HTTP Endpoint",
    summary="Standard MCP endpoint (stateless Streamable HTTP, JSON responses)",
)
async def handle_standard_mcp(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    money: AgentMoney = Depends(get_agent_money),
) -> Response:
    """Handle one standard MCP JSON-RPC message.

    Supports initialize, notifications (202), ping, tools/list, and
    tools/call with server-minted permits. Batch requests are rejected per
    the 2025-06-18 revision.
    """
    _require_enabled()
    _validate_origin(request)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _jsonrpc_error(None, -32700, "Parse error")

    if isinstance(body, list):
        return _jsonrpc_error(None, -32600, "Batch requests are not supported")
    if not isinstance(body, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request")

    method = body.get("method")
    request_id = body.get("id")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if not isinstance(method, str):
        return _jsonrpc_error(request_id, -32600, "Invalid Request")

    # Messages without an id are notifications: accept and do not reply.
    if request_id is None:
        return Response(status_code=202)

    if method == "initialize":
        return JSONResponse(
            {"jsonrpc": "2.0", "id": request_id, "result": _initialize_result(params)}
        )

    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {}})

    if method == "tools/list":
        result = await _handle_tools_list(params)
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    if method == "tools/call":
        return await _standard_tools_call(
            request, body, params, request_id, auth, money
        )

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


@router.api_route("", methods=["GET", "DELETE"], include_in_schema=False)
async def standard_mcp_no_stream(
    auth: AuthContext = Depends(get_auth_context),
) -> Response:
    """Stateless server: no server-initiated stream, no session to delete."""
    _require_enabled()
    return Response(status_code=405, headers={"Allow": "POST"})
