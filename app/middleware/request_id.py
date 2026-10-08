"""Request IDs plus per-request structured logging and metrics.

Every HTTP response leaves this gateway carrying an ``X-Request-ID``
header. A caller may supply its own ID; when it does not, or when the
supplied value is unusable, the gateway mints one. The same ID is bound to
the structlog context for the life of the request, so all log lines the
request produces can be tied together, and it is recorded with the
in-process metrics counters.

Unhandled exceptions are converted here into a fixed-shape 500 response
that carries the request ID but never the exception text. Exception detail
goes to the server log only, where the request ID lets an operator match
the log line to the caller-visible ID.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.request_metrics import record_request

REQUEST_ID_HEADER = "X-Request-ID"
_MAX_REQUEST_ID_LENGTH = 128

# Caller-supplied IDs travel in a header and end up in logs and metric
# labels, so accept only a conservative token shape. Anything else is
# treated as absent and replaced with a minted ID.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._~:-]{1,128}\Z")

_logger = logging.getLogger(__name__)


def resolve_request_id(incoming: str | None) -> str:
    """Return the caller's ID when usable, else mint a fresh one."""
    if incoming and len(incoming) <= _MAX_REQUEST_ID_LENGTH:
        if _VALID_REQUEST_ID.match(incoming):
            return incoming
    return uuid.uuid4().hex


def _route_template(request: Request) -> str | None:
    """Best-effort route template for metric labels, else None."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return None


def _bind_request_id(request_id: str) -> None:
    try:
        import structlog

        structlog.contextvars.bind_contextvars(request_id=request_id)
    except ImportError:
        pass


def _unbind_request_id() -> None:
    try:
        import structlog

        structlog.contextvars.unbind_contextvars("request_id")
    except ImportError:
        pass


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Stamp every request with an ID, log it, and count it."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        _bind_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency = time.perf_counter() - started
            record_request(
                route_template=_route_template(request),
                method=request.method,
                raw_path=request.url.path,
                status_code=500,
                latency_seconds=latency,
            )
            _logger.exception(
                "unhandled exception",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            _unbind_request_id()
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "Unexpected error. Quote request_id when asking for help.",
                    "request_id": request_id,
                },
                headers={REQUEST_ID_HEADER: request_id},
            )
        latency = time.perf_counter() - started
        record_request(
            route_template=_route_template(request),
            method=request.method,
            raw_path=request.url.path,
            status_code=response.status_code,
            latency_seconds=latency,
        )
        response.headers.setdefault(REQUEST_ID_HEADER, request_id)
        _logger.info(
            "request finished",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "route": _route_template(request),
                "status_code": response.status_code,
                "latency_seconds": latency,
            },
        )
        _unbind_request_id()
        return response
