"""
Replay Protection Middleware
============================
Rejects replayed state-changing requests.

A mutating request (POST/PUT/PATCH/DELETE) that carries an ``Idempotency-Key``
header is claimed exactly once per ``(api key, method, path, key)`` tuple via the
durable state backend. A repeat within the retention window is rejected with
``409`` so a captured request cannot be re-executed to double-charge or repeat a
side effect.

This is replay *rejection*, not Stripe-style cached-response idempotency: a
replay returns ``409`` rather than the original response body. That is the right
semantic for the anti-replay trust primitive; response caching could be layered
on later for retry-safety.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import get_settings
from .durable_state import get_durable_state

logger = logging.getLogger(__name__)

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ReplayProtectionMiddleware(BaseHTTPMiddleware):
    """Claim-once guard for mutating requests carrying an idempotency key."""

    def __init__(self, app):
        super().__init__(app)
        settings = get_settings()
        self._enabled = settings.REPLAY_PROTECTION_ENABLED
        self._require_key = settings.REPLAY_PROTECTION_REQUIRE_KEY
        self._ttl = settings.REPLAY_PROTECTION_TTL_SECONDS
        self._header = settings.IDEMPOTENCY_KEY_HEADER
        self._api_key_header = settings.API_KEY_HEADER

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._enabled or request.method not in _MUTATING_METHODS:
            return await call_next(request)  # type: ignore[no-any-return]

        idem_key = request.headers.get(self._header, "").strip()
        api_key = request.headers.get(self._api_key_header, "").strip()

        if not idem_key:
            if self._require_key and api_key:
                return JSONResponse(
                    status_code=428,
                    content={
                        "detail": {
                            "error": "idempotency_key_required",
                            "message": (
                                f"{self._header} header is required for "
                                "state-changing requests."
                            ),
                        }
                    },
                )
            return await call_next(request)  # type: ignore[no-any-return]

        # Scope the nonce to the caller so tenants cannot collide on or probe
        # each other's keyspace. Hash the API key so raw keys never reach storage.
        caller = (
            hashlib.sha256(api_key.encode()).hexdigest()[:32] if api_key else "anon"
        )
        nonce = f"idem:{caller}:{request.method}:{request.url.path}:{idem_key}"

        try:
            claimed = await get_durable_state().claim_once(nonce, self._ttl)
        except Exception:
            # Fail open on unexpected store errors (availability over strictness),
            # consistent with the rate limiter. Signed-permit nonces fail closed.
            logger.exception("replay_protection_store_error; allowing request")
            return await call_next(request)  # type: ignore[no-any-return]

        if not claimed:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": {
                        "error": "request_replayed",
                        "message": (
                            "This request was already processed. Reusing an "
                            f"{self._header} within the retention window is "
                            "not allowed."
                        ),
                        "idempotency_key": idem_key,
                    }
                },
                headers={"Idempotency-Replayed": "true"},
            )

        return await call_next(request)  # type: ignore[no-any-return]
