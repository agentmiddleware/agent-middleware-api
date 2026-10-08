"""Typed errors for the AWI Python SDK.

The client raises these instead of bare :class:`httpx.HTTPStatusError`
for the failure modes callers must handle differently: bad credentials,
permit refusals, and idempotency conflicts on the governed execute route.

Every error below subclasses :class:`httpx.HTTPStatusError`, so existing
code that catches ``httpx.HTTPStatusError`` keeps working.
"""

from __future__ import annotations

from typing import Any

import httpx


class AWIError(Exception):
    """Base class for all AWI SDK failures."""


class AWIAPIError(AWIError, httpx.HTTPStatusError):
    """The API returned an error status with a parsed detail message."""

    def __init__(
        self,
        detail: str,
        *,
        response: httpx.Response,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail
        self.status_code = response.status_code
        self.payload = payload or {}
        httpx.HTTPStatusError.__init__(self, detail, request=response.request, response=response)


class AuthenticationError(AWIAPIError):
    """The API key was missing or invalid (HTTP 401)."""


class AuthorizationError(AWIAPIError):
    """The key is valid but may not perform this action (HTTP 403)."""


class PermitDeniedError(AuthorizationError):
    """A governed call was refused by its permit (HTTP 403, permit error)."""


class IdempotencyConflictError(AWIAPIError):
    """An idempotency key was reused for a different request (HTTP 409)."""


def _error_code(response: httpx.Response) -> tuple[str, dict[str, Any]]:
    """Return the server ``error`` code and payload dict, best effort."""
    try:
        body = response.json()
    except Exception:
        return "", {}
    if isinstance(body, dict):
        error = body.get("error", "")
        message = body.get("message", "")
        code = error if isinstance(error, str) else ""
        text = message if isinstance(message, str) else code
        return code, {"error": code, "message": text}
    return "", {}


def raise_for_status(response: httpx.Response) -> None:
    """Raise a typed SDK error for error statuses, else return silently.

    Unmapped statuses (including redirects, which this SDK never
    follows so the API key cannot leak) fall through to
    ``response.raise_for_status``, preserving the previous bare
    ``httpx.HTTPStatusError`` behavior.
    """
    if response.is_success:
        return
    code, payload = _error_code(response)
    message = payload.get("message") or payload.get("error") or response.text
    status = response.status_code
    if status == 401:
        raise AuthenticationError(message, response=response, payload=payload)
    if status == 403:
        if code.startswith("permit"):
            raise PermitDeniedError(message, response=response, payload=payload)
        raise AuthorizationError(message, response=response, payload=payload)
    if status == 409 and ("idempot" in code or "conflict" in code):
        raise IdempotencyConflictError(message, response=response, payload=payload)
    response.raise_for_status()


__all__ = [
    "AWIAPIError",
    "AWIError",
    "AuthenticationError",
    "AuthorizationError",
    "IdempotencyConflictError",
    "PermitDeniedError",
    "raise_for_status",
]
