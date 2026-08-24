"""x402 facilitation helpers for the middleware settle endpoint.

Client-side only: detect an HTTP 402 payment demand on a response, extract
its ``X-402-*`` headers, and ask the trust plane to authorize and settle it
against a permit. The dict ``settle_402`` returns carries the
transfer-authorization payload the *payer wallet* must sign — this SDK holds
no on-chain keys and signs nothing itself; the middleware's role is
facilitation (permit budget authorization, shadow-ledger metering, signed
receipt), never on-chain settlement.
"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    IdempotencyConflictError,
    PermitDeniedError,
    TransportError,
)

_AMOUNT_HEADER = "x-402-amount"
_PAY_TO_HEADER = "x-402-payto"
_NETWORK_HEADER = "x-402-network"


def _detail_from(payload: dict[str, Any], fallback: str) -> str:
    """Extract the API's error detail string (mirrors client.py's helper)."""
    detail = payload.get("detail")
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        nested = detail.get("error") or detail.get("detail")
        if isinstance(nested, str) and nested:
            return nested
    error = payload.get("error")
    if isinstance(error, str) and error:
        return error
    return fallback


def parse_402_response(response: Any) -> dict[str, Any] | None:
    """Extract the x402 payment requirement from a 402 response, or ``None``.

    Duck-types ``httpx.Response``: anything with a ``status_code`` attribute
    and a ``headers`` mapping works. Returns ``None`` for a non-402 status
    and for a 402 that does not carry the full ``X-402-*`` header set (not an
    x402 demand). Header values are returned as received — the middleware's
    ``/v1/x402`` endpoints are the strict validator.
    """
    if getattr(response, "status_code", None) != 402:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    lowered = {str(key).lower(): str(value) for key, value in dict(headers).items()}
    amount = lowered.get(_AMOUNT_HEADER)
    pay_to = lowered.get(_PAY_TO_HEADER)
    network = lowered.get(_NETWORK_HEADER)
    if amount is None or pay_to is None or network is None:
        return None
    return {"amount": amount, "pay_to": pay_to, "network": network}


class X402Client:
    """Minimal async client for the ``/v1/x402`` facilitation surface."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.thisisatest.tech",
        timeout: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "User-Agent": "b2a-sdk/0.5.0",
            },
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    async def settle_402(
        self,
        *,
        permit_id: str,
        wallet_id: str,
        requirement: dict[str, Any],
        idempotency_key: str,
        payer: str | None = None,
    ) -> dict[str, Any]:
        """POST the requirement to ``/v1/x402/settle`` and return the settlement.

        ``requirement`` is the dict from :func:`parse_402_response` (keys
        ``amount``/``pay_to``/``network``, optional ``asset``); ``payer`` is
        the payer wallet's on-chain address — required by the server for EVM
        networks so the attested EIP-712 message binds the real ``from``. The
        server response includes the transfer authorization for the payer
        wallet to sign plus the settlement receipt id.
        """
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key must not be blank")
        if len(key) > 128:
            raise ValueError("idempotency_key must be at most 128 characters")
        amount = requirement.get("amount", requirement.get("amount_usd"))
        body: dict[str, Any] = {
            "permit_id": permit_id,
            "wallet_id": wallet_id,
            "amount": str(amount) if amount is not None else "",
            "pay_to": requirement.get("pay_to", ""),
            "network": requirement.get("network", ""),
        }
        asset = requirement.get("asset")
        if asset:
            body["asset"] = asset
        if payer is not None:
            body["payer"] = payer
        try:
            response = await self._client.post(
                "/v1/x402/settle",
                json=body,
                headers={"Idempotency-Key": key},
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"POST /v1/x402/settle failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                "invalid_json_response",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise APIError(
                "invalid_object_response",
                status_code=response.status_code,
            )
        if response.is_error:
            detail = _detail_from(payload, f"HTTP {response.status_code}")
            if response.status_code == 401:
                raise AuthenticationError(
                    detail, status_code=401, payload=payload
                )
            # Permit denials arrive as 400 (denied reason) or 404 (not found)
            # with a permit_* detail; surface them as the typed permit error.
            if detail.startswith("permit_"):
                raise PermitDeniedError(detail, payload=payload)
            if response.status_code == 403:
                raise AuthorizationError(detail, status_code=403, payload=payload)
            if response.status_code == 409:
                raise IdempotencyConflictError(
                    detail, status_code=409, payload=payload
                )
            raise APIError(detail, status_code=response.status_code, payload=payload)
        return payload

    async def handle_402(
        self,
        response: Any,
        *,
        permit_id: str,
        wallet_id: str,
        idempotency_key: str,
        payer: str | None = None,
    ) -> dict[str, Any] | None:
        """Parse a 402 response and settle it in one step.

        Returns ``None`` when the response is not an x402 payment demand;
        otherwise the settlement dict, whose ``authorization`` the payer
        wallet signs before the caller retries the original request.
        """
        requirement = parse_402_response(response)
        if requirement is None:
            return None
        return await self.settle_402(
            permit_id=permit_id,
            wallet_id=wallet_id,
            requirement=requirement,
            idempotency_key=idempotency_key,
            payer=payer,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> X402Client:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


__all__ = ["X402Client", "parse_402_response"]
