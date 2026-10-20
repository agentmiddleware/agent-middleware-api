"""Optional OpenTelemetry tracing for the governed MCP path.

Importing this module does not import OpenTelemetry. With
``OTEL_TRACING_ENABLED`` false, or with the otel extra absent, every
helper is a no-op and no exporter is configured.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from inspect import signature
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SPAN_NAMES = frozenset(
    {
        "http.request",
        "mcp.invoke",
        "mcp.reserve",
        "mcp.dispatch_claim",
        "mcp.upstream_dispatch",
        "mcp.receipt",
    }
)
_SAFE_VALUE = re.compile(r"[A-Za-z0-9._:/-]{1,128}\Z")
_WALLET_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_ATTRIBUTES = frozenset(
    {"tool.name", "outcome.state", "wallet.id_hash", "attempt.id"}
)
_PROPAGATE: ContextVar[bool] = ContextVar("otel_propagate_upstream", default=False)
_configured = False


class _FilteredSpan:
    """Forward only allowlisted attributes to the real span."""

    def __init__(self, span: Any) -> None:
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        if key not in _ALLOWED_ATTRIBUTES or type(value) is not str:
            return
        if key == "wallet.id_hash":
            if _WALLET_HASH.fullmatch(value) is None:
                return
        elif _SAFE_VALUE.fullmatch(value) is None:
            return
        try:
            self._span.set_attribute(key, value)
        except Exception:
            return

    def __getattr__(self, name: str) -> Any:
        return getattr(self._span, name)


class _NoopSpan:
    """Stand-in so callers can set attributes without a tracer."""

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def is_recording(self) -> bool:
        return False


_NOOP = _NoopSpan()


def otel_packages_available() -> bool:
    """True only when api, sdk, and the OTLP exporter all import."""
    try:
        import opentelemetry.exporter.otlp.proto.http.trace_exporter  # noqa: F401
        import opentelemetry.sdk.trace  # noqa: F401
        import opentelemetry.trace  # noqa: F401
    except ImportError:
        return False
    return True


def tracing_enabled() -> bool:
    """Enabled only when the operator opted in and the packages import."""
    if not get_settings().OTEL_TRACING_ENABLED:
        return False
    return otel_packages_available()


def _safe_token(value: Any) -> str | None:
    if type(value) is not str or _SAFE_VALUE.fullmatch(value) is None:
        return None
    return value


def _wallet_hash(wallet_id: Any) -> str | None:
    token = _safe_token(wallet_id)
    if token is None:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def note(
    span: Any,
    *,
    tool_name: Any = None,
    outcome_state: Any = None,
    wallet_id: Any = None,
    attempt_id: Any = None,
) -> None:
    """Set only the allowlisted attributes. Wallet ids are stored as a hash."""
    setter = getattr(span, "set_attribute", None)
    if setter is None:
        return
    values = {
        "tool.name": _safe_token(tool_name),
        "outcome.state": _safe_token(outcome_state),
        "wallet.id_hash": _wallet_hash(wallet_id),
        "attempt.id": _safe_token(attempt_id),
    }
    for key, value in values.items():
        if value is None:
            continue
        try:
            setter(key, value)
        except Exception:
            return


def otlp_traces_endpoint(configured: str) -> str | None:
    """HTTP OTLP traces URL from ``OTEL_EXPORTER_OTLP_ENDPOINT``.

    The standard variable is a base URL (``http://host:4318``). The HTTP
    exporter sends traces to ``{base}/v1/traces``. A value that already ends
    in that path is kept. Empty means "let the exporter read the environment".
    """
    endpoint = configured.strip()
    if not endpoint:
        return None
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return endpoint.rstrip("/") + "/v1/traces"


def _install_otlp_provider() -> None:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    settings = get_settings()
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
    )
    endpoint = otlp_traces_endpoint(settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def _ensure_configured() -> None:
    """Install the OTLP provider once, unless a provider is already active."""
    global _configured
    if _configured or not tracing_enabled():
        return
    from opentelemetry import trace
    from opentelemetry.trace import ProxyTracerProvider

    if not isinstance(trace.get_tracer_provider(), ProxyTracerProvider):
        _configured = True
        return
    _install_otlp_provider()
    _configured = True


@asynccontextmanager
async def start_span(
    name: str,
    *,
    tool_name: Any = None,
    outcome_state: Any = None,
    wallet_id: Any = None,
    attempt_id: Any = None,
) -> AsyncIterator[Any]:
    """Open a current span, or yield a no-op when tracing is off.

    Exceptions from the wrapped body propagate. The span does not record
    exception messages or request data. A tracer failure yields a no-op
    instead of failing the governed call.
    """
    if name not in _SPAN_NAMES or not tracing_enabled():
        yield _NOOP
        return
    propagate: Token[bool] | None = None
    try:
        _ensure_configured()
        from opentelemetry import trace

        context_manager = trace.get_tracer("agent-middleware").start_as_current_span(
            name,
            record_exception=False,
            set_status_on_exception=False,
        )
    except Exception:
        logger.warning("otel_span_unavailable", extra={"span": name})
        yield _NOOP
        return
    if name == "mcp.upstream_dispatch":
        propagate = _PROPAGATE.set(True)
    try:
        with context_manager as span:
            filtered = _FilteredSpan(span)
            note(
                filtered,
                tool_name=tool_name,
                outcome_state=outcome_state,
                wallet_id=wallet_id,
                attempt_id=attempt_id,
            )
            yield filtered
    finally:
        if propagate is not None:
            _PROPAGATE.reset(propagate)


def traced_span(
    name: str, **field_map: str
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Wrap an async function in ``start_span``.

    ``field_map`` maps ``start_span`` fields to the wrapped function's
    parameter names, for example ``tool_name="public_tool_id"``.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        sig = signature(fn)

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind_partial(*args, **kwargs)
            span_kwargs: dict[str, Any] = {}
            for span_field, param_name in field_map.items():
                if param_name in bound.arguments:
                    span_kwargs[span_field] = bound.arguments[param_name]
            async with start_span(name, **span_kwargs):
                return await fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__qualname__ = fn.__qualname__
        return wrapper

    return decorator


def inject_w3c_traceparent(carrier: Any) -> None:
    """Add a W3C traceparent header when an upstream-dispatch span is current.

    No-op when tracing is off, when this is not an upstream dispatch, or when
    the carrier does not accept header assignment. Failures are swallowed so
    a client that cannot carry headers still dispatches.
    """
    if not _PROPAGATE.get() or not tracing_enabled():
        return
    if getattr(carrier, "__setitem__", None) is None:
        return
    try:
        from opentelemetry.propagate import inject

        inject(carrier)
    except Exception:
        return


class TracingMiddleware:
    """ASGI middleware that opens ``http.request`` without reading the body."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or not tracing_enabled():
            await self.app(scope, receive, send)
            return
        try:
            _ensure_configured()
            from opentelemetry import trace

            context_manager = trace.get_tracer(
                "agent-middleware"
            ).start_as_current_span(
                "http.request",
                record_exception=False,
                set_status_on_exception=False,
            )
        except Exception:
            logger.warning("otel_span_unavailable", extra={"span": "http.request"})
            await self.app(scope, receive, send)
            return
        with context_manager:
            await self.app(scope, receive, send)


def install_tracing(app: Any) -> None:
    """Attach the HTTP span middleware when tracing is on and packages import.

    Disabled tracing does not add middleware and does not configure a provider.
    """
    if not tracing_enabled():
        return
    try:
        _ensure_configured()
    except Exception:
        logger.warning(
            "otel_tracing_disabled", extra={"reason": "exporter_init_failed"}
        )
        return
    app.add_middleware(TracingMiddleware)
