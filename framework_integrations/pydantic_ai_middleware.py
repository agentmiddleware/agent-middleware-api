"""Governed Pydantic AI middleware over the in-process permit validator.

``governed_tool`` wraps an async function as a client-side stub for a
middleware-registered MCP tool. Each call is screened by the session's
:class:`~b2a_sdk.edge_client.LocalPermitValidator` — a locally-denied call
raises ``b2a_sdk.errors.PermitDeniedError`` without touching the server —
and then dispatched through the governed loop
(``AgentMiddlewareClient.invoke_tool``: permit, caller-owned idempotency
key, signed receipt). The wrapped function's body never runs locally; its
name, signature, and docstring describe the tool to the framework.

Honesty note: the local checks are an optimistic latency mirror. The
governed loop is the path; the server's ``authorize_and_reserve`` remains
authoritative and can still deny a call the local mirror allowed.

This module works with NEITHER framework installed: the generic
``governed_tool`` decorator has no framework dependency, and only
:func:`as_pydantic_ai_tool` imports ``pydantic_ai`` — inside the function,
following the pattern in ``framework_integrations/tools.py``.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import uuid
from decimal import Decimal
from typing import Any, Callable

try:
    from b2a_sdk.edge_client import GovernedEdgeSession
except ImportError as exc:  # pragma: no cover - depends on checkout layout
    raise ImportError(
        "framework_integrations middleware requires the b2a_sdk package. "
        "From a repository checkout run: pip install -e b2a_sdk "
        "(or add b2a_sdk/src to PYTHONPATH)."
    ) from exc


def governed_tool(
    session: GovernedEdgeSession,
    *,
    tool_name: str | None = None,
    credits_hint: Decimal | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory: turn an async stub into a governed tool call.

    The wrapped function must be async; a sync function gets a wrapper that
    raises ``RuntimeError`` at call time (matching ``b2a_sdk.decorators
    .billable``'s established behavior). On each call the wrapper:

    1. consumes an ``idempotency_key`` keyword if the caller supplied one,
       otherwise derives a fresh ``uuid4().hex`` per call — retries that must
       replay (same receipt, no double charge) therefore need a caller-owned
       key; an auto-derived key makes every call a new invocation;
    2. binds the remaining arguments to the stub's signature and runs the
       session's local permit check (``credits_hint`` feeds the budget
       check), raising ``PermitDeniedError`` locally on denial;
    3. invokes the tool through the governed loop and returns the tool
       result — ``structuredContent`` when present, else the MCP content
       list. The typed ``Receipt`` of the most recent call is attached to
       the wrapper as ``wrapper.last_receipt``.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        name = tool_name or func.__name__
        signature = inspect.signature(func)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            idempotency_key = kwargs.pop("idempotency_key", None) or uuid.uuid4().hex
            bound = signature.bind(*args, **kwargs)
            arguments = dict(bound.arguments)
            result = await session.invoke(
                name,
                arguments,
                idempotency_key=str(idempotency_key),
                estimated_credits=credits_hint,
            )
            async_wrapper.last_receipt = result.receipt
            if result.structured_content is not None:
                return result.structured_content
            return result.content

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(
                f"@governed_tool requires an async function. "
                f"Got sync function: {func.__name__}"
            )

        if asyncio.iscoroutinefunction(func):
            async_wrapper.last_receipt = None
            return async_wrapper
        return sync_wrapper

    return decorator


def as_pydantic_ai_tool(
    session: GovernedEdgeSession,
    func: Callable[..., Any],
    *,
    tool_name: str | None = None,
    credits_hint: Decimal | None = None,
) -> Any:
    """Return a ``pydantic_ai.Tool`` that dispatches through the governed loop.

    ``pydantic_ai`` is imported inside this function so the module (and the
    generic ``governed_tool`` path) loads without the framework installed.
    """
    try:
        from pydantic_ai import Tool
    except ImportError as exc:
        raise ImportError(
            "Pydantic AI not installed. Run: pip install pydantic-ai"
        ) from exc

    wrapped = governed_tool(session, tool_name=tool_name, credits_hint=credits_hint)(
        func
    )
    return Tool(
        wrapped,
        name=tool_name or func.__name__,
        description=inspect.getdoc(func) or "",
    )


class PydanticAIGovernedTools:
    """Bind one :class:`GovernedEdgeSession` and mint governed tools from it.

    ``wrap`` is the framework-free decorator (usable directly in tests and
    plain agents); ``as_tool`` additionally packages the wrapper as a
    ``pydantic_ai.Tool`` and therefore needs pydantic_ai installed.
    """

    def __init__(self, session: GovernedEdgeSession) -> None:
        self.session = session

    def wrap(
        self,
        func: Callable[..., Any] | None = None,
        *,
        tool_name: str | None = None,
        credits_hint: Decimal | None = None,
    ) -> Callable[..., Any]:
        decorator = governed_tool(
            self.session, tool_name=tool_name, credits_hint=credits_hint
        )
        return decorator(func) if func is not None else decorator

    def as_tool(
        self,
        func: Callable[..., Any],
        *,
        tool_name: str | None = None,
        credits_hint: Decimal | None = None,
    ) -> Any:
        return as_pydantic_ai_tool(
            self.session, func, tool_name=tool_name, credits_hint=credits_hint
        )


__all__ = ["PydanticAIGovernedTools", "as_pydantic_ai_tool", "governed_tool"]
