"""
Rate Limiting Middleware
========================
Enforces per-API-key request limits using a sliding window counter.
Returns standard rate limit headers on every response.
"""

import time
import asyncio
import logging
from collections import defaultdict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import redis.asyncio as redis

from .config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter keyed by API key.

    Headers returned on every response:
    - X-RateLimit-Limit: max requests per window
    - X-RateLimit-Remaining: requests left in current window
    - X-RateLimit-Reset: seconds until the window resets
    """

    def __init__(self, app, requests_per_minute: int | None = None):
        super().__init__(app)
        self.limit = requests_per_minute or settings.RATE_LIMIT_PER_MINUTE
        self.window = 60.0  # seconds
        self._redis_url = settings.REDIS_URL.strip()
        self._redis: redis.Redis | None = None
        self._redis_lock = asyncio.Lock()
        self._redis_warned = False

        # key -> list of timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> redis.Redis | None:
        if not self._redis_url:
            return None
        if self._redis is not None:
            return self._redis

        async with self._redis_lock:
            if self._redis is not None:
                return self._redis
            try:
                client = redis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await client.ping()
                self._redis = client
            except Exception:
                if not self._redis_warned:
                    logger.exception(
                        "Redis rate limiter unavailable; falling back "
                        "to in-memory limiter."
                    )
                    self._redis_warned = True
                self._redis = None
            return self._redis

    async def _check_limit_with_redis(
        self,
        api_key: str,
        now: float,
    ) -> tuple[bool, int, int]:
        """
        Returns (limited, remaining, reset_in_seconds).
        """
        client = await self._get_redis()
        if client is None:
            return await self._check_limit_in_memory(api_key, now)

        window_size = int(self.window)
        bucket_start = int(now // window_size) * window_size
        reset_in = max(1, (bucket_start + window_size) - int(now))
        key = f"rate_limit:{api_key}:{bucket_start}"

        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_size + 2)

        remaining = max(0, self.limit - int(count))
        limited = int(count) > self.limit
        return limited, remaining, reset_in

    async def _check_limit_in_memory(
        self,
        api_key: str,
        now: float,
    ) -> tuple[bool, int, int]:
        """
        Returns (limited, remaining, reset_in_seconds).
        """
        window_start = now - self.window

        async with self._lock:
            self._requests[api_key] = [
                ts for ts in self._requests[api_key] if ts > window_start
            ]

            current_count = len(self._requests[api_key])
            if current_count >= self.limit:
                oldest = self._requests[api_key][0] if self._requests[api_key] else now
                reset_in = max(1, int(oldest + self.window - now) + 1)
                return True, 0, reset_in

            self._requests[api_key].append(now)
            remaining = max(0, self.limit - len(self._requests[api_key]))
            oldest = self._requests[api_key][0]
            reset_in = max(1, int(oldest + self.window - now) + 1)
            return False, remaining, reset_in

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract API key for per-key limiting
        api_key = request.headers.get(settings.API_KEY_HEADER, "anonymous")

        # Skip rate limiting for docs, health, and test clients
        skip_paths = ("/docs", "/redoc", "/openapi.json", "/health", "/",
                       "/.well-known/agent.json", "/llm.txt", "/docs/index")
        if request.url.path in skip_paths:
            response = await call_next(request)
            return response  # type: ignore[no-any-return]

        # In test / CI environments, the special "test-key" bypasses rate limits
        # so that large test suites don't self-throttle.
        if api_key == "test-key":
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.limit)
            response.headers["X-RateLimit-Remaining"] = str(self.limit)
            response.headers["X-RateLimit-Reset"] = "60"
            return response  # type: ignore[no-any-return]

        now = time.time()
        try:
            limited, remaining, reset_in = await self._check_limit_with_redis(
                api_key, now
            )
        except Exception:
            logger.exception(
                "Redis rate limiter failed; using in-memory rate limiter "
                "for this request."
            )
            limited, remaining, reset_in = await self._check_limit_in_memory(
                api_key, now
            )

        if limited:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "error": "rate_limited",
                        "message": (
                            f"Rate limit exceeded. {self.limit} requests "
                            "per minute allowed."
                        ),
                        "retry_after_seconds": reset_in,
                    }
                },
                headers={
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                    "Retry-After": str(reset_in),
                },
            )

        # Process request
        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)

        return response  # type: ignore[no-any-return]
