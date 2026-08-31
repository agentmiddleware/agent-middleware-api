"""
Rate Limiting Middleware
========================
Enforces per-API-key request limits using a sliding window counter.
Returns standard rate limit headers on every response.
"""

import asyncio
import hashlib
import ipaddress
import logging
import os
import time

import redis.asyncio as redis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import get_settings
from .runtime_degradation import mark_rate_limiter_memory_fallback
from .trust_mode import is_production_like_environment

settings = get_settings()
logger = logging.getLogger(__name__)

_PUBLIC_MCP_PATH = "/mcp/public"
_PUBLIC_MCP_BUCKET_PREFIX = "route:mcp-public"
_PUBLIC_MCP_GLOBAL_LIMIT_MULTIPLIER = 10
_PRIVATE_BUCKET_PREFIX = "route:authenticated"
_DEFAULT_MAX_MEMORY_BUCKETS = 10_000


def _public_mcp_client_id(request: Request) -> str:
    """Return a non-spoofable client identifier for the supported ingress.

    Railway documents ``X-Real-IP`` as an ingress-populated client address.
    Trust it only when Railway's injected environment marker is present, and
    only when exactly one canonical IP value was supplied. Other deployments
    retain the ASGI peer address and ignore all caller-provided forwarding
    headers.
    """

    peer_host = request.client.host if request.client else "unknown"
    if not os.environ.get("RAILWAY_ENVIRONMENT_ID", "").strip():
        return peer_host

    values = request.headers.getlist("x-real-ip")
    if len(values) != 1:
        return peer_host
    raw = values[0].strip()
    if not raw or "," in raw or "%" in raw:
        return peer_host
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError:
        return peer_host


def _private_credential_bucket(request: Request) -> str:
    """Hash the credential selected by the authentication precedence rules."""
    authorization = request.headers.get("authorization")
    if authorization is not None:
        credential = f"authorization:{authorization}"
    else:
        api_key = request.headers.get(settings.API_KEY_HEADER, "anonymous")
        credential = f"api-key:{api_key}"
    digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    namespace = f"{settings.STATE_NAMESPACE}:{settings.PUBLIC_URL or settings.APP_NAME}"
    return f"{namespace}:{_PRIVATE_BUCKET_PREFIX}:credential:{digest}"


class RateLimiterUnavailable(RuntimeError):
    """Raised when Redis rate limiting is required but unavailable."""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter keyed by API key.

    Headers returned on every response:
    - X-RateLimit-Limit: max requests per window
    - X-RateLimit-Remaining: requests left in current window
    - X-RateLimit-Reset: seconds until the window resets
    """

    def __init__(
        self,
        app,
        requests_per_minute: int | None = None,
        max_memory_buckets: int = _DEFAULT_MAX_MEMORY_BUCKETS,
    ):
        super().__init__(app)
        self.limit = requests_per_minute or settings.RATE_LIMIT_PER_MINUTE
        self.window = 60.0  # seconds
        self._redis_url = settings.REDIS_URL.strip()
        self._redis: redis.Redis | None = None
        self._redis_lock = asyncio.Lock()
        self._redis_warned = False

        # key -> list of timestamps. Invalid credentials reach this middleware
        # before authentication, so the map must remain bounded even when a
        # caller rotates a fresh bogus value on every request.
        self._requests: dict[str, list[float]] = {}
        self._overflow_requests: list[float] = []
        self._max_memory_buckets = max(1, max_memory_buckets)
        self._lock = asyncio.Lock()

    def _fail_closed_on_redis_outage(self) -> bool:
        """Production-like + REDIS_URL configured → no silent memory fallback."""
        return bool(
            self._redis_url and is_production_like_environment(settings.ENVIRONMENT)
        )

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
                mark_rate_limiter_memory_fallback()
                if not self._redis_warned:
                    logger.exception(
                        "Redis rate limiter unavailable; %s.",
                        (
                            "failing closed (production-like)"
                            if self._fail_closed_on_redis_outage()
                            else "falling back to in-memory limiter"
                        ),
                    )
                    self._redis_warned = True
                self._redis = None
            return self._redis

    async def _check_limit_with_redis(
        self,
        bucket_key: str,
        now: float,
        *,
        limit: int | None = None,
    ) -> tuple[bool, int, int]:
        """
        Returns (limited, remaining, reset_in_seconds).
        """
        effective_limit = self.limit if limit is None else limit
        client = await self._get_redis()
        if client is None:
            if self._fail_closed_on_redis_outage():
                raise RateLimiterUnavailable("redis_rate_limiter_unavailable")
            if self._redis_url:
                mark_rate_limiter_memory_fallback()
            return await self._check_limit_in_memory(
                bucket_key,
                now,
                limit=effective_limit,
            )

        window_size = int(self.window)
        bucket_start = int(now // window_size) * window_size
        reset_in = max(1, (bucket_start + window_size) - int(now))
        key = f"rate_limit:{bucket_key}:{bucket_start}"

        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_size + 2)

        remaining = max(0, effective_limit - int(count))
        limited = int(count) > effective_limit
        return limited, remaining, reset_in

    async def _check_limit_in_memory(
        self,
        bucket_key: str,
        now: float,
        *,
        limit: int | None = None,
    ) -> tuple[bool, int, int]:
        """
        Returns (limited, remaining, reset_in_seconds).
        """
        effective_limit = self.limit if limit is None else limit
        window_start = now - self.window

        async with self._lock:
            if (
                bucket_key not in self._requests
                and len(self._requests) >= self._max_memory_buckets
            ):
                expired = [
                    key
                    for key, timestamps in self._requests.items()
                    if not any(ts > window_start for ts in timestamps)
                ]
                for key in expired:
                    del self._requests[key]

            overflow = (
                bucket_key not in self._requests
                and len(self._requests) >= self._max_memory_buckets
            )
            if overflow:
                timestamps = [ts for ts in self._overflow_requests if ts > window_start]
                self._overflow_requests = timestamps
            else:
                timestamps = [
                    ts for ts in self._requests.get(bucket_key, []) if ts > window_start
                ]
                self._requests[bucket_key] = timestamps

            current_count = len(timestamps)
            if current_count >= effective_limit:
                oldest = timestamps[0] if timestamps else now
                reset_in = max(1, int(oldest + self.window - now) + 1)
                return True, 0, reset_in

            timestamps.append(now)
            remaining = max(0, effective_limit - len(timestamps))
            oldest = timestamps[0]
            reset_in = max(1, int(oldest + self.window - now) + 1)
            return False, remaining, reset_in

    async def dispatch(self, request: Request, call_next) -> Response:
        # Public MCP is intentionally unauthenticated. Ignore caller-supplied
        # API-key headers there so rotating bogus values cannot mint fresh
        # rate-limit buckets (and the local test-key bypass cannot be reached
        # from the Internet).
        public_mcp_request = request.url.path.rstrip("/") == _PUBLIC_MCP_PATH
        if public_mcp_request:
            client_id = _public_mcp_client_id(request)
            namespace = (
                f"{settings.STATE_NAMESPACE}:{settings.PUBLIC_URL or settings.APP_NAME}"
            )
            bucket_limits = [
                (
                    f"{namespace}:{_PUBLIC_MCP_BUCKET_PREFIX}:client:{client_id}",
                    self.limit,
                ),
                (
                    f"{namespace}:{_PUBLIC_MCP_BUCKET_PREFIX}:global",
                    max(
                        self.limit,
                        self.limit * _PUBLIC_MCP_GLOBAL_LIMIT_MULTIPLIER,
                    ),
                ),
            ]
        else:
            bucket_key = _private_credential_bucket(request)
            bucket_limits = [(bucket_key, self.limit)]

        # Skip rate limiting for docs, health, and test clients
        skip_paths = (
            "/docs",
            "/redoc",
            "/openapi.json",
            "/health",
            "/",
            "/.well-known/agent.json",
            "/llm.txt",
            "/llms.txt",
            "/docs/index",
            "/WEDGE.md",
            "/SECURITY_LIMITATIONS.md",
            "/DESIGN_PARTNER_GUIDE.md",
            "/docs/partner-api-key-bootstrap.md",
        )
        if request.url.path in skip_paths:
            response = await call_next(request)
            return response  # type: ignore[no-any-return]

        # In test / CI environments, the special "test-key" bypasses rate limits
        # so that large test suites don't self-throttle.
        if (
            not public_mcp_request
            and request.headers.get("authorization") is None
            and request.headers.get(settings.API_KEY_HEADER) == "test-key"
            and not is_production_like_environment(settings.ENVIRONMENT)
        ):
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.limit)
            response.headers["X-RateLimit-Remaining"] = str(self.limit)
            response.headers["X-RateLimit-Reset"] = "60"
            return response  # type: ignore[no-any-return]

        now = time.time()
        applied_limit = self.limit
        header_remaining = self.limit
        header_reset = int(self.window)
        try:
            for index, (bucket_key, applied_limit) in enumerate(bucket_limits):
                limited, remaining, reset_in = await self._check_limit_with_redis(
                    bucket_key,
                    now,
                    limit=applied_limit,
                )
                if index == 0:
                    header_remaining = remaining
                    header_reset = reset_in
                if limited:
                    break
        except RateLimiterUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "error": "rate_limiter_unavailable",
                        "message": (
                            "Shared rate limiter (Redis) is unavailable. "
                            "In-memory fallback is refused in production-like "
                            "environments."
                        ),
                    }
                },
                headers={
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "30",
                },
            )
        except Exception:
            mark_rate_limiter_memory_fallback()
            if self._fail_closed_on_redis_outage():
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": {
                            "error": "rate_limiter_unavailable",
                            "message": (
                                "Shared rate limiter (Redis) failed. "
                                "In-memory fallback is refused in "
                                "production-like environments."
                            ),
                        }
                    },
                    headers={
                        "X-RateLimit-Limit": str(self.limit),
                        "X-RateLimit-Remaining": "0",
                        "Retry-After": "30",
                    },
                )
            logger.exception(
                "Redis rate limiter failed; using in-memory rate limiter "
                "for this request."
            )
            for index, (bucket_key, applied_limit) in enumerate(bucket_limits):
                limited, remaining, reset_in = await self._check_limit_in_memory(
                    bucket_key,
                    now,
                    limit=applied_limit,
                )
                if index == 0:
                    header_remaining = remaining
                    header_reset = reset_in
                if limited:
                    break

        if limited:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "error": "rate_limited",
                        "message": (
                            f"Rate limit exceeded. {applied_limit} requests "
                            "per minute allowed."
                        ),
                        "retry_after_seconds": reset_in,
                    }
                },
                headers={
                    "X-RateLimit-Limit": str(applied_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                    "Retry-After": str(reset_in),
                },
            )

        # Process request
        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(header_remaining)
        response.headers["X-RateLimit-Reset"] = str(header_reset)

        return response  # type: ignore[no-any-return]
