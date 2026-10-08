"""Opt-in ``Idempotency-Key`` replay protection for state-changing HTTP routes.

Shared by the billing provisioning routes and API-key issuance: begin a record
on the way in (replaying a stored response, or 409-ing on a conflicting
reuse), and complete it with the terminal outcome so a retry with the same key
gets the original result instead of repeating the side effect.

Caller contract for money-moving routes (charge, transfer, wallet
provisioning, key issuance):

- Send one key per money intent, as a non-blank string of at most 128
  characters with no control characters. A present-but-unusable key is
  refused with ``400 invalid_idempotency_key`` before anything is charged,
  matching the governed MCP surfaces.
- Retry with the same key and the same payload after a timeout or an
  unclear outcome. The retry replays the original response.
- Expect ``409 idempotency_in_progress`` when the first attempt is still
  running: wait, then retry the same key to collect the original result.
- Expect ``409 idempotency_key_reused`` when the key was already used for
  a different payload. Never reuse a key for a different amount or
  destination; mint a fresh key per new intent.
- No key at all means no replay protection: a retried request runs again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from ..services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyService,
    InvalidIdempotencyKeyError,
    decode_idempotency_key_header,
    get_idempotency_service,
    validate_client_idempotency_key,
)


def validate_http_idempotency_key(raw_key: str) -> str:
    """Validate a caller-supplied ``Idempotency-Key`` header value.

    Same contract as the governed MCP surfaces: the header bytes are
    re-read as UTF-8 and the key must be a non-blank string of at most
    128 characters with no control characters. Raises ``HTTPException``
    400 carrying the machine-actionable ``invalid_idempotency_key`` detail
    before any permit, debit, or record is promised.
    """
    try:
        return validate_client_idempotency_key(
            decode_idempotency_key_header(raw_key),
            source="Idempotency-Key header",
        )
    except InvalidIdempotencyKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), **exc.as_error_data()},
        ) from exc


@dataclass
class IdempotencyGuard:
    """Opt-in replay protection for a state-changing money endpoint.

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
) -> tuple[IdempotencyGuard, JSONResponse | None]:
    """Start (or replay) an idempotent operation. Returns the guard plus an
    optional replay response to return immediately."""
    if not idempotency_key:
        return IdempotencyGuard(None, wallet_id, endpoint, None), None
    idempotency_key = validate_http_idempotency_key(idempotency_key)
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
