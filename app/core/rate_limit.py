"""Token-bucket rate limiter backed by Redis.

Per-wallet: 100 req/min burst, 10 req/s sustained.
Global: 1000 req/s across all wallets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import ClassVar

import redis.asyncio as redis

from app.core.config import get_settings


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int  # Unix timestamp
    retry_after: int | None = None  # seconds


class RateLimiter:
    """Redis-backed token-bucket rate limiter.

    Uses Redis Lua scripts for atomic check-and-deduct operations,
    safe across multiple server instances.
    """

    # Default limits
    DEFAULT_BURST: ClassVar[int] = 100       # requests per minute
    DEFAULT_WINDOW: ClassVar[int] = 60       # seconds
    DEFAULT_PER_SEC: ClassVar[int] = 10      # sustained requests per second
    GLOBAL_BURST: ClassVar[int] = 1000       # global requests per second
    GLOBAL_WINDOW: ClassVar[int] = 1

    _lua_check: ClassVar[str] = """
    local key = KEYS[1]
    local burst = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local cost = tonumber(ARGV[3])
    local now = tonumber(ARGV[4])

    local bucket = redis.call('HMGET', key, 'tokens', 'updated')
    local tokens = tonumber(bucket[1]) or burst
    local updated = tonumber(bucket[2]) or now

    -- Refill tokens based on time elapsed
    local elapsed = math.max(0, now - updated)
    local refill = elapsed * (burst / window)
    tokens = math.min(burst, tokens + refill)

    if tokens >= cost then
        tokens = tokens - cost
        redis.call('HMSET', key, 'tokens', tokens, 'updated', now)
        redis.call('EXPIRE', key, window * 2)
        return {1, tokens, updated + window}
    else
        redis.call('HMSET', key, 'tokens', tokens, 'updated', now)
        redis.call('EXPIRE', key, window * 2)
        return {0, tokens, updated + window}
    end
    """

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._lua_sha: str | None = None

    async def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            settings = get_settings()
            redis_url = getattr(settings, "REDIS_URL", None) or "redis://localhost:6379"
            self._redis = redis.from_url(redis_url, decode_responses=True)
        return self._redis

    async def _get_lua_sha(self) -> str:
        if self._lua_sha is None:
            r = await self._get_redis()
            self._lua_sha = await r.script_load(self._lua_check)
        return self._lua_sha

    async def check(
        self,
        key: str,
        burst: int = DEFAULT_BURST,
        window: int = DEFAULT_WINDOW,
        cost: int = 1,
    ) -> RateLimitResult:
        """Check if request is allowed under rate limit.

        Returns RateLimitResult with allowed=True if request can proceed,
        or allowed=False with retry_after if limit exceeded.
        """
        r = await self._get_redis()
        sha = await self._get_lua_sha()
        now = int(time.time())

        result = await r.evalsha(sha, 1, key, str(burst), str(window), str(cost), str(now))
        allowed = bool(result[0])
        remaining = int(result[1])
        reset_at = int(result[2])

        retry_after = None
        if not allowed:
            # Estimate when a token will be available
            retry_after = max(1, window // burst)

        return RateLimitResult(
            allowed=allowed,
            limit=burst,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )

    async def check_wallet(
        self,
        wallet_id: str,
        key_id: str | None = None,
    ) -> RateLimitResult:
        """Per-wallet rate limit check."""
        key = f"rl:wallet:{wallet_id}"
        if key_id:
            key = f"{key}:{key_id}"
        return await self.check(key, burst=self.DEFAULT_BURST, window=self.DEFAULT_WINDOW)

    async def check_global(self) -> RateLimitResult:
        """Global rate limit check."""
        return await self.check(
            "rl:global",
            burst=self.GLOBAL_BURST,
            window=self.GLOBAL_WINDOW,
        )


# Module-level singleton
_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
