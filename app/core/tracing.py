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
from typing import Any, Literal

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_tracing_failure_logged = False

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
            _log_tracing_failure_once()
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
    """True only when api, sdk, and the OTLP exporter all import.

    A broken install can raise more than ``ImportError`` (for example a
    ``TypeError`` from protobuf descriptors). Any failure means tracing is
    unavailable, not that the process should abort.
    """
    try:
        import opentelemetry.exporter.otlp.proto.http.trace_exporter  # noqa: F401
        import opentelemetry.sdk.trace  # noqa: F401
        import opentelemetry.trace  # noqa: F401
    except Exception:
        return False
    return True


def tracing_enabled() -> bool:
    """Enabled only when the operator opted in and the packages import."""
    try:
        if not get_settings().OTEL_TRACING_ENABLED:
            return False
        return otel_packages_available()
    except Exception:
        return False


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
            _log_tracing_failure_once()
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


def _log_tracing_failure_once() -> None:
    """Log the first tracing failure at debug and ignore the rest.

    A broken tracer, provider, or processor must not flood logs, and the
    message carries no span data.
    """
    global _tracing_failure_logged
    if _tracing_failure_logged:
        return
    _tracing_failure_logged = True
    logger.debug("otel_tracing_failure")


class _FailOpenSpan:
    """Run the body even when the tracer fails on start, enter, or end.

    ``start_as_current_span`` returns a lazy context manager. Processor
    callbacks run on ``__enter__`` and ``__exit__``, outside the call that
    merely constructs it. Those exceptions are swallowed. The wrapped body
    still runs once, and an exception it raises propagates unchanged.
    """

    def __init__(self, opener: Callable[[], Any]) -> None:
        self._opener = opener
        self._context_manager: Any = None
        self._entered = False

    def __enter__(self) -> Any:
        try:
            self._context_manager = self._opener()
            span = self._context_manager.__enter__()
        except Exception:
            _log_tracing_failure_once()
            self._context_manager = None
            self._entered = False
            return _NOOP
        self._entered = True
        return _FilteredSpan(span)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        if self._entered and self._context_manager is not None:
            try:
                self._context_manager.__exit__(exc_type, exc, tb)
            except Exception:
                _log_tracing_failure_once()
        return False


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

    Exceptions from the wrapped body propagate unchanged. The span does not
    record exception messages or request data. A tracer, provider, or
    processor failure while starting, entering, ending, or writing the span
    yields a no-op instead of failing the governed call. The body runs once.
    """
    try:
        active = name in _SPAN_NAMES and tracing_enabled()
    except Exception:
        logger.warning("otel_tracing_unavailable")
        active = False
    if not active:
        yield _NOOP
        return

    def open_span() -> Any:
        _ensure_configured()
        from opentelemetry import trace

        return trace.get_tracer("agent-middleware").start_as_current_span(
            name,
            record_exception=False,
            set_status_on_exception=False,
        )

    propagate: Token[bool] | None = None
    with _FailOpenSpan(open_span) as span:
        if name == "mcp.upstream_dispatch" and span is not _NOOP:
            try:
                propagate = _PROPAGATE.set(True)
            except Exception:
                _log_tracing_failure_once()
                propagate = None
        try:
            note(
                span,
                tool_name=tool_name,
                outcome_state=outcome_state,
                wallet_id=wallet_id,
                attempt_id=attempt_id,
            )
            yield span
        finally:
            if propagate is not None:
                try:
                    _PROPAGATE.reset(propagate)
                except Exception:
                    _log_tracing_failure_once()

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
        _log_tracing_failure_once()
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
        try:
            active = scope.get("type") == "http" and tracing_enabled()
        except Exception:
            logger.warning("otel_tracing_unavailable")
            active = False
        if not active:
            await self.app(scope, receive, send)
            return

        def open_span() -> Any:
            _ensure_configured()
            from opentelemetry import trace

            return trace.get_tracer("agent-middleware").start_as_current_span(
                "http.request",
                record_exception=False,
                set_status_on_exception=False,
            )

        with _FailOpenSpan(open_span):
            await self.app(scope, receive, send)


def install_tracing(app: Any) -> None:
    """Attach the HTTP span middleware when tracing is on and packages import.

    Disabled tracing does not add middleware and does not configure a provider.
    A broken OpenTelemetry install leaves tracing off and logs a warning
    instead of aborting startup.
    """
    try:
        if not get_settings().OTEL_TRACING_ENABLED:
            return
        if not otel_packages_available():
            logger.warning("otel_tracing_install_failed")
            return
        _ensure_configured()
        app.add_middleware(TracingMiddleware)
    except Exception:
        logger.warning("otel_tracing_install_failed")
        return
