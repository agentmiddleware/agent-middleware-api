"""Rate limiting middleware for FastAPI."""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.rate_limit import get_rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply token-bucket rate limiting to all requests.

    Checks global limit first, then per-wallet limit.
    Returns 429 with Retry-After header if exceeded.
    """

    async def dispatch(self, request: Request, call_next):
        limiter = get_rate_limiter()

        # 1. Global rate limit
        global_result = await limiter.check_global()
        if not global_result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Global rate limit exceeded. Please slow down.",
                },
                headers={
                    "X-RateLimit-Limit": str(global_result.limit),
                    "X-RateLimit-Remaining": str(global_result.remaining),
                    "X-RateLimit-Reset": str(global_result.reset_at),
                    "Retry-After": str(global_result.retry_after or 1),
                },
            )

        # 2. Per-wallet rate limit (if wallet identified)
        wallet_id = getattr(request.state, "wallet_id", None)
        key_id = getattr(request.state, "key_id", None)

        if wallet_id:
            wallet_result = await limiter.check_wallet(wallet_id, key_id)
            if not wallet_result.allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": "Wallet rate limit exceeded. Please slow down.",
                    },
                    headers={
                        "X-RateLimit-Limit": str(wallet_result.limit),
                        "X-RateLimit-Remaining": str(wallet_result.remaining),
                        "X-RateLimit-Reset": str(wallet_result.reset_at),
                        "Retry-After": str(wallet_result.retry_after or 1),
                    },
                )

            # Add rate limit headers to successful responses
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(wallet_result.limit)
            response.headers["X-RateLimit-Remaining"] = str(wallet_result.remaining)
            response.headers["X-RateLimit-Reset"] = str(wallet_result.reset_at)
            return response

        return await call_next(request)
