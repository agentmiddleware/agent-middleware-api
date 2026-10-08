"""Request ID assignment and propagation (RFC 9110 request correlation).

Several routers read an inbound ``X-Request-ID`` header and attach it to
audit and billing-governance records, but nothing in the stack assigned one:
responses never carried it, so a caller could not correlate a receipt or an
error with its own logs, and a request without the header left no handle at
all. Worse, the raw header value flowed straight into the audit
``request_id`` column, which caps at 100 characters, so one overlong value
could fail the audit write (and with it the request) on a length-enforcing
database.

Fixed here at the ASGI boundary, outside every other layer: the first
inbound ``X-Request-ID`` that is 1 to 128 characters of letters, digits,
``.``, ``_`` or ``-`` is kept; anything else (absent, overlong, odd
characters, or several competing values) is replaced by a generated
``uuid4().hex``. The normalized value is the only one downstream ever sees:
scope headers are rewritten to a single entry, ``scope["state"]`` carries it
for code that prefers state, and the response carries it back so the caller
can match request to receipt. An explicitly set response value is left alone.

Pure ASGI (no ``BaseHTTPMiddleware``) so short-circuit responses produced by
inner layers, CORS preflights included, are stamped on the way out without
being buffered.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Awaitable, Callable

HEADER_NAME = "x-request-id"

# Existing callers already send values like "req-billing-governance" and
# "policy-planner-tier"; this pattern accepts those while refusing spaces,
# control characters, and anything that could smuggle log or header breaks.
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")

# The audit request_id column caps at 100 characters; 128 stays comfortably
# inside it while leaving room for operator prefixes.
_MAX_INBOUND_LENGTH = 128


def normalize_request_id(values: list[str]) -> str:
    """Return the caller ID to keep, or a generated one when none qualifies."""
    for value in values:
        if len(value) <= _MAX_INBOUND_LENGTH and _SAFE_ID.match(value):
            return value
    return uuid.uuid4().hex


class RequestIdMiddleware:
    """Assign every request a safe ID and send it back on the response."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == HEADER_NAME.encode("latin-1")
        ]
        request_id = normalize_request_id(inbound)

        # Downstream reads request.headers, so rewrite to exactly one entry.
        # Anything the caller sent that did not qualify is gone from here on.
        scope["headers"] = [
            (name, value)
            for name, value in scope.get("headers", [])
            if name.lower() != HEADER_NAME.encode("latin-1")
        ] + [(b"x-request-id", request_id.encode("latin-1"))]
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                if not any(
                    name.lower() == HEADER_NAME.encode("latin-1") for name, _ in headers
                ):
                    headers.append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_id)
