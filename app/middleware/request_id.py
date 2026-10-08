"""Propagate or mint a per-request ID for log correlation.

Several routers already read ``X-Request-ID`` from the inbound headers, but
nothing ever set it: concurrent requests were indistinguishable in the logs
and a caller-supplied ID was echoed nowhere. This middleware closes that
gap. It accepts a caller-supplied ID when it looks like an opaque token,
mints one (uuid4 hex) otherwise, stores it on ``request.state.request_id``
for handlers, binds it to structlog contextvars so every structured log
line in the request carries it, and returns it in the response header so a
caller can quote it back in an incident report.

A hostile or malformed inbound value is replaced, never trusted: header
values end up in logs and response headers, so only a bounded alphabet is
accepted.
"""

from __future__ import annotations

import re
import uuid

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# Opaque token alphabet: letters, digits, and a few separators. Bounded so a
# caller cannot smuggle log-forging newlines or oversized values through.
_VALID_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")


def resolve_request_id(inbound: str | None) -> str:
    """Return the inbound ID when it is a safe token, else a fresh one."""
    if inbound and _VALID_ID.match(inbound.strip()):
        return inbound.strip()
    return uuid.uuid4().hex


def _bind_structlog(request_id: str) -> None:
    try:
        from structlog import contextvars as structlog_contextvars
    except ImportError:
        return
    structlog_contextvars.bind_contextvars(request_id=request_id)


def _unbind_structlog() -> None:
    try:
        from structlog import contextvars as structlog_contextvars
    except ImportError:
        return
    structlog_contextvars.unbind_contextvars("request_id")


class RequestIDMiddleware:
    """Ensure every HTTP request carries a request ID end to end."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        # Starlette's request.state is backed by this dict, so handlers see
        # the same value via request.state.request_id.
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id

        _bind_structlog(request_id)
        try:

            async def send_with_id(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append(
                        (
                            REQUEST_ID_HEADER.lower().encode("latin-1"),
                            request_id.encode("latin-1"),
                        )
                    )
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_id)
        finally:
            _unbind_structlog()
