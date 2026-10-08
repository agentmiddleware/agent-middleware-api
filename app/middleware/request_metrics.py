"""Record per-request latency and status counts for /metrics.

Kept separate from RequestIDMiddleware on purpose: identity belongs on
every response even if metric collection is ever disabled, and either
layer can be reasoned about alone.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.observability_metrics import record_request


def _route_label(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    raw = scope.get("path")
    return raw if isinstance(raw, str) and raw else "unknown"


class RequestMetricsMiddleware:
    """Time each HTTP response and fold it into the process-local counters."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status_code = 500

        async def send_capture(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_capture)
        finally:
            record_request(_route_label(scope), status_code, time.monotonic() - start)
