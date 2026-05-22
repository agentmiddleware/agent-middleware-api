"""Protocol-neutral governed-invocation adapter seam.

The trust plane governs *actions*, not a particular wire protocol. An adapter
normalizes a protocol-specific request into a :class:`GovernedRequest`, runs it
through the single governed-invocation pipeline (permit validation, policy
evaluation, idempotency, metering, signed receipt, audit), and normalizes the
:class:`GovernedResult` back into the protocol's response shape.

MCP is the first and currently only adapter. It delegates to the existing
governed path in ``app.routers.mcp`` (``_execute_registered_tool``) so there is
exactly one source of truth for governance — the adapter adds a stable seam,
not a second implementation. Other protocols (AWI, browser, WebMCP) can be
added later by implementing the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.auth import AuthContext
from app.services.agent_money import AgentMoney


@dataclass
class GovernedRequest:
    """A protocol-neutral, governable tool invocation."""

    protocol: str
    tool_name: str
    arguments: dict[str, Any]
    wallet_id: str | None
    auth: AuthContext
    money: AgentMoney
    permit_id: str | None = None
    idempotency_key: str | None = None
    transport: str = "adapter"
    endpoint: str = "/mcp/messages"
    request_id: str | None = None
    request_payload: dict[str, Any] | None = None


@dataclass
class GovernedResult:
    """The outcome of a governed invocation, protocol-neutral."""

    protocol: str
    raw: dict[str, Any]
    is_error: bool = False
    receipt: dict[str, Any] | None = None
    outcome: str | None = None
    ledger_entry_id: str | None = None
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GovernedInvocationAdapter(ABC):
    """Base class for protocol adapters into the governed invocation pipeline."""

    protocol: str

    @abstractmethod
    async def normalize_request(self, raw: Any, **context: Any) -> GovernedRequest:
        """Translate a protocol-specific request into a GovernedRequest."""

    @abstractmethod
    async def invoke(self, request: GovernedRequest) -> GovernedResult:
        """Run the request through the governed invocation pipeline."""

    @abstractmethod
    async def normalize_response(self, result: GovernedResult) -> dict[str, Any]:
        """Translate a GovernedResult back into the protocol's response shape."""


class McpGovernedAdapter(GovernedInvocationAdapter):
    """First adapter: Model Context Protocol (JSON-RPC ``tools/call``)."""

    protocol = "mcp"

    async def normalize_request(self, raw: Any, **context: Any) -> GovernedRequest:
        """Translate an MCP ``tools/call`` body into a GovernedRequest.

        Required context: ``auth`` (AuthContext) and ``money`` (AgentMoney).
        Optional: ``transport``, ``endpoint``, ``request_id``,
        ``idempotency_key``, ``request_payload``.
        """
        auth: AuthContext = context["auth"]
        money: AgentMoney = context["money"]
        idempotency_key: str | None = context.get("idempotency_key")

        params = raw.get("params", raw)
        mcp_context = params.get("mcpContext", {}) or {}
        return GovernedRequest(
            protocol=self.protocol,
            tool_name=params.get("name"),
            arguments=params.get("arguments", {}) or {},
            wallet_id=mcp_context.get("wallet_id"),
            auth=auth,
            money=money,
            permit_id=mcp_context.get("permit_id"),
            idempotency_key=idempotency_key or mcp_context.get("idempotency_key"),
            transport=context.get("transport", "adapter"),
            endpoint=context.get("endpoint", "/mcp/messages"),
            request_id=context.get("request_id"),
            request_payload=context.get("request_payload"),
        )

    async def invoke(self, request: GovernedRequest) -> GovernedResult:
        """Run the governed pipeline.

        Governance failures (denials, insufficient funds, tool errors) are
        raised as the pipeline's typed exceptions and propagate to the caller,
        which owns the protocol-specific error envelope. This keeps a single
        source of truth for both the happy path and the error semantics.
        """
        # Lazy import: the MCP router pulls in many services at import time, and
        # this keeps the trust package import-light and free of cycles.
        from app.routers.mcp import _execute_registered_tool

        raw = await _execute_registered_tool(
            tool_name=request.tool_name,
            arguments=request.arguments,
            wallet_id=request.wallet_id,
            auth=request.auth,
            money=request.money,
            transport=request.transport,
            endpoint=request.endpoint,
            request_id=request.request_id,
            permit_id=request.permit_id,
            idempotency_key=request.idempotency_key,
            request_payload=request.request_payload,
        )

        receipt = raw.get("receipt") if isinstance(raw, dict) else None
        return GovernedResult(
            protocol=self.protocol,
            raw=raw,
            is_error=bool(raw.get("isError")) if isinstance(raw, dict) else False,
            receipt=receipt,
            outcome=(receipt or {}).get("outcome"),
            ledger_entry_id=(receipt or {}).get("ledger_entry_id"),
        )

    async def normalize_response(self, result: GovernedResult) -> dict[str, Any]:
        return result.raw


__all__ = [
    "GovernedRequest",
    "GovernedResult",
    "GovernedInvocationAdapter",
    "McpGovernedAdapter",
]
