"""Typed SDK errors for authentication and governed tool calls."""

from __future__ import annotations

from typing import Any


class AgentMiddlewareError(Exception):
    """Base class for all SDK-specific failures."""


class APIError(AgentMiddlewareError):
    """The API returned an error or an invalid response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail
        self.status_code = status_code
        self.payload = payload or {}
        super().__init__(detail)


class TransportError(AgentMiddlewareError):
    """The request could not be completed at the HTTP transport boundary."""


class AuthenticationError(APIError):
    """The supplied API key was missing or invalid."""


class AuthorizationError(APIError):
    """The authenticated key cannot access the requested resource."""


class PermitDeniedError(AuthorizationError):
    """A governed invocation was denied by its permit.

    ``status_code`` defaults to 403, which is what the governed invoke path
    uses. Callers that saw a different HTTP status (x402 settle returns 400
    or 404 for a real permit denial) pass that status through so a retry
    decision can tell a denial from a transient failure.
    """

    def __init__(
        self,
        reason: str,
        *,
        receipt_id: str | None = None,
        payload: dict[str, Any] | None = None,
        status_code: int = 403,
    ) -> None:
        self.reason = reason
        self.receipt_id = receipt_id
        super().__init__(reason, status_code=status_code, payload=payload)


def _coerce_shortfall(value: Any) -> float | None:
    """Return a finite shortfall, or None when the server value is unusable.

    Booleans are rejected on purpose: ``True`` is an ``int``, and
    ``float(True)`` would report a one-credit shortfall the server did not send.
    """
    if isinstance(value, bool) or value is None or value == "unknown":
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


class IdempotencyConflictError(APIError):
    """An idempotency key is in progress or was reused for another request."""


class DeliveryUncertainError(APIError):
    """The upstream dispatch occurred, but its outcome cannot be confirmed."""

    def __init__(
        self,
        *,
        receipt_id: str,
        detail: str = "delivery_uncertain",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.receipt_id = receipt_id
        super().__init__(detail, status_code=504, payload=payload)


class InsufficientFundsError(APIError):
    """The wallet does not have enough credits for an operation.

    The positional constructor remains compatible with the provisional 0.3 SDK.
    """

    def __init__(
        self,
        wallet_id: str,
        shortfall: Any = None,
        top_up_url: str | None = None,
        *,
        receipt_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.wallet_id = wallet_id
        self.shortfall = _coerce_shortfall(shortfall)
        self.top_up_url = top_up_url
        self.receipt_id = receipt_id
        message = f"Insufficient funds in wallet {wallet_id}. Shortfall: {self.shortfall} credits."
        if top_up_url:
            message = f"{message} Top up at: {top_up_url}"
        super().__init__(message, status_code=402, payload=payload)


__all__ = [
    "APIError",
    "AgentMiddlewareError",
    "AuthenticationError",
    "AuthorizationError",
    "DeliveryUncertainError",
    "IdempotencyConflictError",
    "InsufficientFundsError",
    "PermitDeniedError",
    "TransportError",
]
