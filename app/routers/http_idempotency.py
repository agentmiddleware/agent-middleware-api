"""``Idempotency-Key`` replay protection for state-changing HTTP routes.

Shared by the billing money routes and API-key issuance: begin a record on
the way in (replaying a stored response, or 409-ing on a conflicting reuse),
and complete it with the terminal outcome so a retry with the same key gets
the original result instead of repeating the side effect.

Protection is opt-in by default: a request without a key runs unprotected, as
before. When ``REQUIRE_IDEMPOTENCY_KEY`` is true, money-moving routes pass
``require_key=True`` and a keyless request is refused with
``400 idempotency_key_required`` before anything is minted, charged, or
moved. A key that is present is validated in both modes, matching the MCP
transport: a present-but-unusable value is refused rather than treated as
absent, which would turn the caller's retry into a second side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from ..core.config import get_settings
from ..services.idempotency import (
    IDEMPOTENCY_KEY_HEADER_SOURCE,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyService,
    InvalidIdempotencyKeyError,
    get_idempotency_service,
    validate_client_idempotency_key,
)


def billing_idempotency_required() -> bool:
    """Whether money routes must see an ``Idempotency-Key`` header.

    Reads ``REQUIRE_IDEMPOTENCY_KEY`` live on every call so tests and
    operators can flip it without a restart. Default false: keyless callers
    keep today's behavior until the operator opts in.
    """
    return bool(get_settings().REQUIRE_IDEMPOTENCY_KEY)


@dataclass
class IdempotencyGuard:
    """Replay protection for a state-changing money endpoint.

    Mirrors the flow already used inline by ``/v1/billing/charge``: begin a
    record on the way in (replaying a stored response, or 409-ing on a
    conflicting reuse), and complete it with the terminal outcome so a retry
    with the same ``Idempotency-Key`` gets the original result instead of
    charging/crediting/transferring twice.
    """

    service: IdempotencyService | None
    wallet_id: str
    endpoint: str
    key: str | None

    async def complete(
        self,
        response_json: dict,
        status_code: int,
        *,
        response_reference: str | None = None,
    ) -> None:
        if not self.service or not self.key:
            return
        await self.service.complete(
            wallet_id=self.wallet_id,
            endpoint=self.endpoint,
            idempotency_key=self.key,
            response_reference=response_reference,
            response_json=response_json,
            status_code=status_code,
        )


async def begin_http_idempotency(
    *,
    idempotency_key: str | None,
    wallet_id: str,
    endpoint: str,
    request_payload: dict[str, Any],
    require_key: bool = False,
) -> tuple[IdempotencyGuard, JSONResponse | None]:
    """Start (or replay) an idempotent operation. Returns the guard plus an
    optional replay response to return immediately.

    A supplied key is validated exactly as the MCP transport validates it
    (non-blank, at most 128 chars, no control characters, never trimmed):
    a present-but-unusable value is refused with
    ``400 invalid_idempotency_key`` instead of being treated as absent.
    When ``require_key`` is true and no key was sent, the call is refused
    with ``400 idempotency_key_required`` before any record is opened.
    """
    if idempotency_key is not None:
        try:
            idempotency_key = validate_client_idempotency_key(
                idempotency_key, source=IDEMPOTENCY_KEY_HEADER_SOURCE
            )
        except InvalidIdempotencyKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": str(exc), **exc.as_error_data()},
            ) from exc
    elif require_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "idempotency_key_required",
                "message": (
                    "This money-moving endpoint requires an Idempotency-Key "
                    "header. Send one unique key per money intent and retry "
                    "with the same key; nothing was minted, charged, or moved."
                ),
            },
        )
    else:
        return IdempotencyGuard(None, wallet_id, endpoint, None), None
    idem = get_idempotency_service()
    try:
        replay = await idem.begin(
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "idempotency_key_reused", "message": str(exc)},
        ) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "idempotency_in_progress", "message": str(exc)},
        ) from exc
    guard = IdempotencyGuard(idem, wallet_id, endpoint, idempotency_key)
    if replay is not None:
        return guard, JSONResponse(
            status_code=replay.status_code, content=replay.response_json
        )
    return guard, None
