"""Standard MCP endpoint (``/mcp``) served by the official MCP SDK.

The official python SDK's Streamable HTTP transport owns the whole protocol
surface: ``initialize`` and capability negotiation, protocol-version
validation, JSON-RPC framing and parse errors, notifications (202), ``ping``,
and error envelopes. This module contributes only what the SDK cannot know —
the trust plane. ``tools/list`` serves the governed manifest, and
``tools/call`` runs the exact same permit -> meter -> exactly-once dispatch ->
signed receipt pipeline as the governed endpoints.

Standard clients cannot supply the wallet/permit context the governed adapter
requires, so ``tools/call`` mints a bounded, signed, single-tool, short-lived
permit on behalf of the caller's wallet (derived from its API key) and then
delegates to the same governed invoke path as ``/mcp/messages``. The full
permit -> meter -> receipt -> audit loop applies unchanged; only the minting
step moves server-side. Bootstrap/admin keys have no wallet and are refused:
there is no wallet to encumber, and this endpoint must never bypass metering.

Replay safety: a client-supplied ``Idempotency-Key`` header (or the
``io.agentmiddleware/idempotency_key`` entry in ``params._meta``) is honored
exactly like the governed endpoints. Without one, each call gets a fresh
generated key, so client retries are charged as new calls — the same contract
as an un-keyed governed invoke.

The endpoint is stateless: each POST gets a fresh SDK transport in JSON mode
(no ``Mcp-Session-Id``, responses are plain JSON, never SSE), so there is no
server-initiated stream and GET/DELETE answer 405. The signed receipt is
returned on every ``tools/call`` result both under
``_meta["io.agentmiddleware/receipt"]`` (the spec's extension point) and as a
top-level ``receipt`` field (the pre-SDK contract). Disabled by default —
``ENABLE_STANDARD_MCP_ENDPOINT`` must be set explicitly, so the surface cannot
be advertised (or preflighted by the registry publish gate) before an operator
turns it on.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import anyio
import mcp.types as mcp_types
from anyio.abc import TaskStatus
from fastapi import APIRouter, Depends, HTTPException, Request
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import RequestBodyLimitMiddleware
from mcp.shared.exceptions import McpError
from starlette.responses import JSONResponse, Response
from starlette.types import Message, Receive, Scope, Send

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
from app.services.agent_money import get_agent_money
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

_IDEMPOTENCY_META_KEY = "io.agentmiddleware/idempotency_key"
_RECEIPT_META_KEY = "io.agentmiddleware/receipt"
_MAX_META_VALUE_LENGTH = 256

# Idempotency scope for auto-minted permits; distinct from the governed-call
# scope so mint replay and call replay never collide.
_AUTO_PERMIT_ENDPOINT = "/mcp#auto-permit"

_SERVER_INSTRUCTIONS = (
    "Governed MCP trust plane. Every tools/call is authorized by a "
    "server-minted, wallet-bounded permit, metered against the caller's "
    "credit balance, and answered with a signed receipt. Authenticate with a "
    "wallet-scoped API key; send an Idempotency-Key header to make retries "
    "replay-safe."
)


def _mcp_error(code: int, message: str, data: dict[str, Any] | None = None) -> McpError:
    return McpError(mcp_types.ErrorData(code=code, message=message, data=data))


# Far above any legitimate MCP message, far below where Python 3.11's JSON
# parser starts raising RecursionError instead of returning a parse result.
_MAX_JSON_NESTING_DEPTH = 100


def _json_nesting_depth_exceeds(body: bytes, limit: int) -> bool:
    """True when raw JSON bytes nest deeper than ``limit`` outside strings."""
    depth = 0
    in_string = False
    escaped = False
    for byte in body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # double quote
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):  # { or [
            depth += 1
            if depth > limit:
                return True
        elif byte in (0x7D, 0x5D):  # } or ]
            depth = max(0, depth - 1)
    return False


def _permit_error(exc: PermitError) -> McpError:
    code = -32004 if exc.reason == "permit_budget_exceeds_wallet_balance" else -32003
    return _mcp_error(code, exc.reason)


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


def _meta_idempotency_key(params: mcp_types.CallToolRequestParams) -> str | None:
    meta = params.meta
    extra = getattr(meta, "model_extra", None) if meta is not None else None
    if not extra:
        return None
    value = extra.get(_IDEMPOTENCY_META_KEY)
    if isinstance(value, str) and 0 < len(value) <= _MAX_META_VALUE_LENGTH:
        return value
    return None


async def _mint_auto_permit(
    *,
    auth: AuthContext,
    tool_name: str,
    record: dict[str, Any],
    client_key: str | None,
) -> str:
    """Mint the bounded single-tool permit backing this call.

    The governed replay hash covers the permit id, so a retried idempotency
    key must resolve to the SAME auto-minted permit — mint through an
    idempotency record keyed off the client's key. Generated keys are unique
    per call and skip this bookkeeping.
    """
    wallet_id = auth.wallet_id
    if not wallet_id:  # narrowed by the caller; fail closed regardless
        raise _mcp_error(-32003, "wallet_scoped_key_required")
    settings = get_settings()
    permit_request = PermitCreateRequest(
        issuer_wallet_id=wallet_id,
        subject_wallet_id=wallet_id,
        subject_key_id=auth.key_id,
        allowed_tools=[tool_name],
        max_credits=_tool_call_budget(record),
        expires_at=utc_now()
        + timedelta(seconds=settings.STANDARD_MCP_PERMIT_TTL_SECONDS),
    )

    if not client_key:
        try:
            permit = await get_permit_service().create_permit(
                permit_request, subject_key_id=auth.key_id
            )
        except PermitError as exc:
            raise _permit_error(exc) from exc
        return permit.permit_id

    idem = get_idempotency_service()
    mint_key = "smcp-" + hashlib.sha256(client_key.encode("utf-8")).hexdigest()[:48]
    mint_payload = {
        "kind": "standard-mcp-auto-permit",
        "tool": tool_name,
        "wallet_id": wallet_id,
        "subject_key_id": auth.key_id,
    }
    try:
        mint_replay = await idem.begin(
            wallet_id=wallet_id,
            endpoint=_AUTO_PERMIT_ENDPOINT,
            idempotency_key=mint_key,
            request_payload=mint_payload,
        )
    except IdempotencyConflictError as exc:
        raise _mcp_error(-32003, "idempotency_key_reused") from exc
    except IdempotencyInProgressError as exc:
        raise _mcp_error(-32003, "idempotency_in_progress") from exc
    if mint_replay and mint_replay.response_json:
        return mint_replay.response_json["permit_id"]

    try:
        permit = await get_permit_service().create_permit(
            permit_request, subject_key_id=auth.key_id
        )
    except PermitError as exc:
        await idem.abandon(
            wallet_id=wallet_id,
            endpoint=_AUTO_PERMIT_ENDPOINT,
            idempotency_key=mint_key,
        )
        raise _permit_error(exc) from exc
    await idem.complete(
        wallet_id=wallet_id,
        endpoint=_AUTO_PERMIT_ENDPOINT,
        idempotency_key=mint_key,
        response_reference=permit.permit_id,
        response_json={"permit_id": permit.permit_id},
        status_code=201,
    )
    return permit.permit_id


async def _governed_tools_call(
    *,
    auth: AuthContext,
    tool_name: str,
    arguments: dict[str, Any],
    client_idempotency_key: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    """Auto-mint the permit, then run the single governed invoke pipeline."""
    if not tool_name:
        raise _mcp_error(-32602, "Missing tool name")

    if not auth.wallet_id:
        raise _mcp_error(
            -32003,
            "wallet_scoped_key_required: this endpoint mints permits from the "
            "caller's wallet; authenticate with a wallet-scoped API key",
        )

    record = get_service_registry().get_local(tool_name)
    if record is None:
        raise _mcp_error(-32001, f"Tool not found: {tool_name}")

    idempotency_key = client_idempotency_key or f"mcp-auto-{uuid.uuid4().hex}"
    permit_id = await _mint_auto_permit(
        auth=auth,
        tool_name=tool_name,
        record=record,
        client_key=client_idempotency_key,
    )

    call_params = {
        "name": tool_name,
        "arguments": arguments,
        "mcpContext": {
            "wallet_id": auth.wallet_id,
            "permit_id": permit_id,
            "idempotency_key": idempotency_key,
        },
    }
    request_payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    try:
        return await _handle_tools_call(
            call_params,
            auth=auth,
            money=get_agent_money(),
            transport="jsonrpc",
            endpoint="/mcp",
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
    except HumanApprovalPendingSignal as e:
        raise _mcp_error(e.jsonrpc_code, str(e), e.data or None) from e
    except ToolPermissionDenied as e:
        data = {"receipt": e.receipt} if e.receipt else None
        raise _mcp_error(-32003, str(e), data) from e
    except GovernedToolError as e:
        data = dict(e.extra_data)
        if e.receipt:
            data["receipt"] = e.receipt
        raise _mcp_error(e.jsonrpc_code, str(e), data or None) from e
    except PermissionError as e:
        raise _mcp_error(-32003, str(e)) from e
    except ValueError as e:
        code = _value_error_jsonrpc_code(str(e))
        if code == -32603:
            logger.error(f"Standard MCP tool call failed: {e}")
        raise _mcp_error(code, str(e)) from e
    except McpError:
        raise
    except Exception as e:
        logger.error(f"Standard MCP tool call failed: {e}")
        raise _mcp_error(-32603, str(e)) from e


def _build_standard_mcp_server() -> Server:
    server = Server(
        McpGenerator.MANIFEST_NAME,
        version=MCP_SERVER_VERSION,
        instructions=_SERVER_INSTRUCTIONS,
    )

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        result = await _handle_tools_list({})
        tools = []
        for tool in result["tools"]:
            payload = dict(tool)
            payload.setdefault("inputSchema", {"type": "object"})
            tools.append(mcp_types.Tool.model_validate(payload))
        return tools

    async def handle_call_tool(
        req: mcp_types.CallToolRequest,
    ) -> mcp_types.ServerResult:
        """Governed tools/call.

        Registered directly (not through the ``@server.call_tool()``
        decorator) so governance denials keep their JSON-RPC error codes and
        receipt-bearing ``data`` instead of collapsing into an ``isError``
        text result.
        """
        ctx = server.request_context
        http_request = ctx.request if isinstance(ctx.request, Request) else None
        auth: AuthContext | None = None
        if http_request is not None:
            auth = http_request.scope.get("state", {}).get("auth_context")
        if auth is None:
            # The ASGI wrapper authenticates every request before the SDK
            # transport runs; a missing context means this handler is being
            # driven by an unexpected transport. Fail closed.
            raise _mcp_error(-32603, "auth_context_missing")

        client_key = None
        if http_request is not None:
            client_key = http_request.headers.get("Idempotency-Key")
        client_key = client_key or _meta_idempotency_key(req.params)

        result = await _governed_tools_call(
            auth=auth,
            tool_name=req.params.name,
            arguments=req.params.arguments or {},
            client_idempotency_key=client_key,
            request_id=str(ctx.request_id) if ctx.request_id is not None else None,
        )

        payload = dict(result)
        receipt = payload.get("receipt")
        if receipt is not None:
            meta = dict(payload.get("_meta") or {})
            meta[_RECEIPT_META_KEY] = receipt
            payload["_meta"] = meta
        return mcp_types.ServerResult(mcp_types.CallToolResult.model_validate(payload))

    server.request_handlers[mcp_types.CallToolRequest] = handle_call_tool
    return server


_standard_mcp_server = _build_standard_mcp_server()


def _require_enabled() -> None:
    if not get_settings().ENABLE_STANDARD_MCP_ENDPOINT:
        raise HTTPException(status_code=404, detail="Not Found")


def _validate_origin(request: Request) -> None:
    """Validate browser Origin exactly and bind production Host to PUBLIC_URL.

    Non-browser MCP clients send no Origin header and pass through.
    """
    public_url = get_settings().PUBLIC_URL.rstrip("/")
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if public_url and request.url.netloc != urlsplit(public_url).netloc:
        raise HTTPException(status_code=421, detail={"error": "host_not_allowed"})

    origin = request.headers.get("origin")
    if not origin:
        return
    # A reverse proxy may expose its internal HTTP scheme through the ASGI
    # request even though the canonical browser origin is HTTPS. Once an
    # operator configures PUBLIC_URL, it is the only origin authority;
    # request-derived origin is a local/unconfigured fallback only.
    allowed = {public_url} if public_url else {request_origin}
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail={"error": "origin_not_allowed"})


class _SdkTransportResponse(Response):
    """Delegates the whole HTTP exchange to a fresh stateless SDK transport.

    Each POST gets its own transport in JSON-response mode — the exact
    composition ``StreamableHTTPSessionManager`` uses per request in stateless
    mode, inlined here so no lifespan-scoped task group is required. The SDK
    owns everything after authentication: JSON-RPC parsing and parse errors,
    Accept/Content-Type validation, lifecycle and protocol-version
    negotiation, notifications, and error envelopes.

    Takes the :class:`Server` to run so every stateless surface (standard,
    public) shares one transport composition instead of drifting copies.
    """

    def __init__(
        self,
        server: Server,
        *,
        max_request_body_size: int | None = None,
    ) -> None:
        super().__init__()
        self._server = server
        self._max_request_body_size = max_request_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._max_request_body_size is not None:
            limited = RequestBodyLimitMiddleware(
                self._handle_request,
                self._max_request_body_size,
            )
            await limited(scope, receive, send)
            return
        await self._handle_request(scope, receive, send)

    async def _handle_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        # Refuse absurdly nested bodies before the SDK parses them. On
        # Python 3.11 json.loads raises RecursionError at ~1000 frames and
        # the SDK's broad handler turns that into a 500; on 3.12+ the parse
        # succeeds and pydantic rejects the depth as invalid params. Scanning
        # the raw bytes gives both versions the same -32602 answer.
        messages: list[Message] = []
        body = bytearray()
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        if _json_nesting_depth_exceeds(bytes(body), _MAX_JSON_NESTING_DEPTH):
            error_response = JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32602,
                        "message": "request JSON exceeds the supported nesting depth",
                    },
                },
                status_code=200,
            )
            await error_response(scope, receive, send)
            return

        replayed = iter(messages)

        async def replay_receive() -> Message:
            for message in replayed:
                return message
            return await receive()

        await self._dispatch_to_transport(scope, replay_receive, send)

    async def _dispatch_to_transport(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=True,
        )

        async with anyio.create_task_group() as tg:

            async def run_server(
                *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED
            ) -> None:
                async with transport.connect() as (read_stream, write_stream):
                    task_status.started()
                    try:
                        await self._server.run(
                            read_stream,
                            write_stream,
                            self._server.create_initialization_options(),
                            stateless=True,
                        )
                    except Exception:  # pragma: no cover - response already sent
                        logger.exception("MCP stateless session crashed")

            await tg.start(run_server)
            await transport.handle_request(scope, receive, send)
            await transport.terminate()


@router.post(
    "",
    name="MCP Streamable HTTP Endpoint",
    summary=(
        "Standard MCP endpoint (official MCP SDK, stateless Streamable HTTP, "
        "JSON responses)"
    ),
)
async def handle_standard_mcp(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> Response:
    """Hand one standard MCP message to the official SDK's transport.

    Authentication and origin validation happen here at the HTTP layer; the
    SDK owns the protocol. The governed ``tools/call`` handler reads the
    authenticated caller back from ``request.state``.
    """
    _require_enabled()
    _validate_origin(request)
    request.scope.setdefault("state", {})["auth_context"] = auth
    return _SdkTransportResponse(_standard_mcp_server)


@router.api_route("", methods=["GET", "DELETE"], include_in_schema=False)
async def standard_mcp_no_stream(
    auth: AuthContext = Depends(get_auth_context),
) -> Response:
    """Stateless server: no server-initiated stream, no session to delete."""
    _require_enabled()
    return Response(status_code=405, headers={"Allow": "POST"})
