"""Wallet-scoped re-plan guard: cross-permit dedup plus a wallet velocity cap.

The per-permit duplicate guard (``MCP_UPSTREAM_DUPLICATE_GUARD``) keys on
``permit_id``. An agent that re-plans under a new idempotency key on
``POST /mcp`` gets a freshly auto-minted permit on every call, so that guard
never sees the repeat, and neither does the permit's own budget. This guard
keys on the wallet instead:

- **Dedup**: one in-flight-or-completed lock per
  (wallet, tool, canonical argument hash) for ``WALLET_DEDUP_WINDOW_SECONDS``,
  owned by the idempotency key that took it. A same-key retry re-enters its
  own lock and is never blocked here (it replays through the idempotency
  record before this guard runs anyway).
- **Velocity**: credits (integer minor units, never float) and call counts
  summed across ALL of the wallet's permits in a fixed window.

Check and record are one atomic step: a single Lua script on Redis, or one
critical section over the in-memory store. A deterministic, uncharged
failure hands both back atomically (``release``); success and ambiguous
outcomes (``delivery_uncertain``, a charge that stands) keep them.

Redis keys share the hash tag ``{wallet}`` so every key for a wallet lands in
one cluster slot and the script's multi-key access is legal on Redis Cluster:
``amw:{<wallet>}:dedup:<digest>``, ``amw:{<wallet>}:vel:credits:<bucket>``,
``amw:{<wallet>}:vel:calls:<bucket>``.

Store selection follows the rate limiter: ``REDIS_URL`` set means a shared
Redis counter (the durable-state backend may be Postgres, whose
``shared_redis`` returns None, so it is not used here). Without ``REDIS_URL``
the guard keeps per-process counters, which bound one process only. With
``REDIS_URL`` set and Redis unreachable, a production-like environment
reports the store unavailable (enforce fails closed and retryable; log_only
allows) and other environments fall back to per-process counters.

``log_only`` must never block: every failure inside the guard, including a
store outage or an argument that cannot be canonicalized, is logged and the
call proceeds.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Any

import redis.asyncio as redis

from app.core.config import (
    WALLET_VELOCITY_MINOR_UNITS_PER_CREDIT,
    ReplanGuardMode,
    get_settings,
)
from app.core.trust_mode import is_production_like_environment
from app.services.argument_canonicalizer import (
    CanonicalizationError,
    canonical_request_hash,
)

logger = logging.getLogger(__name__)

REASON_DUPLICATE = "wallet_duplicate_request"
REASON_VELOCITY = "wallet_velocity_exceeded"
REASON_UNAVAILABLE = "wallet_guard_unavailable"

_STATUS_OK = "ok"
_STATUS_DUPLICATE = "duplicate"
_STATUS_VELOCITY_CREDITS = "velocity_credits"
_STATUS_VELOCITY_CALLS = "velocity_calls"

# Every counter compared in Lua must stay below 2**53 (doubles). Settings bound
# the limits; a single call's cost is clamped here so one absurd price cannot
# push a counter out of exact range (it exceeds any configurable cap anyway).
_MAX_COUNTER_UNITS = 2**52
_OWNER_DOMAIN = b"amw:replan-owner:v1\x00"
_SAFE_TAG = re.compile(r"\A[A-Za-z0-9_.:-]{1,128}\Z")
_MEMORY_SWEEP_THRESHOLD = 4096

# KEYS: dedup, velocity credits, velocity calls.
# ARGV: owner, dedup_ttl_ms, dedup_enabled, cost_units, credits_limit,
#       calls_limit, velocity_ttl_ms, force.
# Returns {status, dedup_held, velocity_applied, credits_after, calls_after};
# the counters come back as integer replies (exact below 2**53).
# ``force`` (log_only) records what an allowed call would record even when the
# decision would deny, so detection keeps working; it never overwrites a lock
# held by another owner.
_ACQUIRE_LUA = """
local owner = ARGV[1]
local dedup_ttl = tonumber(ARGV[2])
local dedup_enabled = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local credits_limit = tonumber(ARGV[5])
local calls_limit = tonumber(ARGV[6])
local vel_ttl = tonumber(ARGV[7])
local force = tonumber(ARGV[8])
local status = 'ok'
local reentrant = 0
if dedup_enabled == 1 then
  local holder = redis.call('GET', KEYS[1])
  if holder then
    if holder == owner then reentrant = 1 else status = 'duplicate' end
  end
end
local credits = tonumber(redis.call('GET', KEYS[2]) or '0')
local calls = tonumber(redis.call('GET', KEYS[3]) or '0')
if reentrant == 1 then
  return {'ok', 1, 0, credits, calls}
end
if status == 'ok' and credits_limit > 0 and credits + cost > credits_limit then
  status = 'velocity_credits'
end
if status == 'ok' and calls_limit > 0 and calls + 1 > calls_limit then
  status = 'velocity_calls'
end
local dedup_held = 0
local applied = 0
if status == 'ok' or force == 1 then
  if dedup_enabled == 1 and status ~= 'duplicate' then
    redis.call('SET', KEYS[1], owner, 'PX', dedup_ttl)
    dedup_held = 1
  end
  credits = redis.call('INCRBY', KEYS[2], cost)
  calls = redis.call('INCR', KEYS[3])
  redis.call('PEXPIRE', KEYS[2], vel_ttl)
  redis.call('PEXPIRE', KEYS[3], vel_ttl)
  applied = 1
end
return {status, dedup_held, applied, credits, calls}
"""

# KEYS: dedup, velocity credits, velocity calls.
# ARGV: owner, release_dedup, refund_velocity, cost_units.
# Only the owner's lock is deleted; counters never go negative.
_RELEASE_LUA = """
local owner = ARGV[1]
if tonumber(ARGV[2]) == 1 and redis.call('GET', KEYS[1]) == owner then
  redis.call('DEL', KEYS[1])
end
if tonumber(ARGV[3]) == 1 then
  local cost = tonumber(ARGV[4])
  local credits = tonumber(redis.call('GET', KEYS[2]) or '0')
  if credits <= cost then
    redis.call('DEL', KEYS[2])
  else
    redis.call('DECRBY', KEYS[2], cost)
  end
  local calls = tonumber(redis.call('GET', KEYS[3]) or '0')
  if calls <= 1 then
    redis.call('DEL', KEYS[3])
  else
    redis.call('DECR', KEYS[3])
  end
end
return 1
"""


class ReplanGuardUnavailable(RuntimeError):
    """The configured shared store could not answer."""


@dataclass(frozen=True)
class ReplanReservation:
    """Exactly what one acquisition recorded, so release undoes only that.

    The velocity keys name the bucket the cost was recorded into: a refund
    after the window rolled over must not decrement a period this call never
    contributed to.
    """

    backend: str
    dedup_key: str
    credits_key: str
    calls_key: str
    owner: str
    dedup_held: bool
    velocity_applied: bool
    cost_units: int


@dataclass
class ReplanDecision:
    allowed: bool
    reason: str | None = None
    would_deny_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    reservation: ReplanReservation | None = None
    retryable: bool = False


def credits_to_minor_units(amount: Decimal) -> int:
    """Exact integer minor units; any finer fraction rounds up (a cap leans tight)."""
    if not amount.is_finite() or amount <= 0:
        return 0
    units = (amount * WALLET_VELOCITY_MINOR_UNITS_PER_CREDIT).to_integral_value(
        rounding=ROUND_CEILING
    )
    return min(int(units), _MAX_COUNTER_UNITS)


def _minor_units_to_credits(units: int) -> str:
    if not units:
        return "0"
    credits = Decimal(units) / WALLET_VELOCITY_MINOR_UNITS_PER_CREDIT
    return format(credits.normalize(), "f")


def _wallet_tag(wallet_id: str) -> str:
    """Hash-tag body for a wallet; braces or odd bytes are hashed away."""
    if _SAFE_TAG.fullmatch(wallet_id):
        return wallet_id
    return "h" + hashlib.sha256(wallet_id.encode("utf-8")).hexdigest()[:32]


def _owner_token(owner: str) -> str:
    return hashlib.sha256(_OWNER_DOMAIN + owner.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class _Request:
    dedup_key: str
    credits_key: str
    calls_key: str
    owner: str
    dedup_ttl_ms: int
    dedup_enabled: bool
    cost_units: int
    credits_limit: int
    calls_limit: int
    velocity_ttl_ms: int
    force: bool


class _MemoryStore:
    """Per-process store with the same semantics as the Lua scripts.

    Each operation runs synchronously under one lock with no await inside,
    so check-and-record is atomic within the process.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, tuple[Any, float]] = {}

    def _get(self, key: str, now: float) -> Any:
        entry = self._values.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at <= now:
            del self._values[key]
            return None
        return value

    def _sweep(self, now: float) -> None:
        if len(self._values) < _MEMORY_SWEEP_THRESHOLD:
            return
        for key in [k for k, (_, exp) in self._values.items() if exp <= now]:
            del self._values[key]

    def acquire(self, req: _Request) -> tuple[str, bool, bool, int, int]:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            status = _STATUS_OK
            reentrant = False
            if req.dedup_enabled:
                holder = self._get(req.dedup_key, now)
                if holder is not None:
                    if holder == req.owner:
                        reentrant = True
                    else:
                        status = _STATUS_DUPLICATE
            credits = int(self._get(req.credits_key, now) or 0)
            calls = int(self._get(req.calls_key, now) or 0)
            if reentrant:
                return _STATUS_OK, True, False, credits, calls
            if (
                status == _STATUS_OK
                and req.credits_limit > 0
                and credits + req.cost_units > req.credits_limit
            ):
                status = _STATUS_VELOCITY_CREDITS
            if (
                status == _STATUS_OK
                and req.calls_limit > 0
                and calls + 1 > req.calls_limit
            ):
                status = _STATUS_VELOCITY_CALLS
            dedup_held = False
            applied = False
            if status == _STATUS_OK or req.force:
                if req.dedup_enabled and status != _STATUS_DUPLICATE:
                    self._values[req.dedup_key] = (
                        req.owner,
                        now + req.dedup_ttl_ms / 1000,
                    )
                    dedup_held = True
                vel_expiry = now + req.velocity_ttl_ms / 1000
                credits += req.cost_units
                calls += 1
                self._values[req.credits_key] = (credits, vel_expiry)
                self._values[req.calls_key] = (calls, vel_expiry)
                applied = True
            return status, dedup_held, applied, credits, calls

    def release(self, res: ReplanReservation) -> None:
        now = time.monotonic()
        with self._lock:
            if res.dedup_held and self._get(res.dedup_key, now) == res.owner:
                del self._values[res.dedup_key]
            if res.velocity_applied:
                for key, amount in (
                    (res.credits_key, res.cost_units),
                    (res.calls_key, 1),
                ):
                    current = self._get(key, now)
                    if current is None:
                        continue
                    if int(current) <= amount:
                        del self._values[key]
                    else:
                        self._values[key] = (
                            int(current) - amount,
                            self._values[key][1],
                        )

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


class ReplanGuard:
    """Check-and-reserve / release over Redis or the per-process store."""

    def __init__(self) -> None:
        self._memory = _MemoryStore()
        self._redis: redis.Redis | None = None
        self._redis_url: str | None = None
        self._redis_lock = asyncio.Lock()

    # -- store selection -------------------------------------------------

    async def _client(self) -> redis.Redis | None:
        """Shared Redis client, None for per-process, or raise unavailable."""
        settings = get_settings()
        url = settings.REDIS_URL.strip()
        if not url:
            return None
        if self._redis is not None and self._redis_url == url:
            return self._redis
        async with self._redis_lock:
            if self._redis is not None and self._redis_url == url:
                return self._redis
            from app.core.rate_limiter import (
                REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
                REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
                REDIS_SOCKET_TIMEOUT_SECONDS,
                enforce_redis_timeouts,
            )

            client = None
            try:
                client = enforce_redis_timeouts(
                    redis.from_url(
                        url,
                        encoding="utf-8",
                        decode_responses=True,
                        socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
                        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
                        health_check_interval=REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
                    )
                )
                await client.ping()
            except Exception as exc:
                if client is not None:
                    await self._close_quietly(client)
                if is_production_like_environment(settings.ENVIRONMENT):
                    raise ReplanGuardUnavailable("redis_unreachable") from exc
                logger.warning(
                    "replan_guard_memory_fallback: REDIS_URL is set but Redis is "
                    "unreachable; using per-process counters (%s)",
                    type(exc).__name__,
                )
                return None
            self._redis = client
            self._redis_url = url
            return client

    async def _drop_client(self, failed: redis.Redis) -> None:
        async with self._redis_lock:
            if self._redis is failed:
                self._redis = None
                self._redis_url = None
        await self._close_quietly(failed)

    @staticmethod
    async def _close_quietly(client: redis.Redis) -> None:
        try:
            await asyncio.wait_for(client.aclose(), timeout=2.0)
        except Exception:
            logger.debug("replan_guard_redis_close_failed", exc_info=True)

    # -- public API ------------------------------------------------------

    async def check_and_reserve(
        self,
        *,
        wallet_id: str,
        tool_name: str,
        arguments: Any,
        owner: str,
        credits: Decimal,
        allow_identical_repeats: bool = False,
    ) -> ReplanDecision:
        """Atomically decide and record; never raises.

        ``log_only`` always returns allowed. ``enforce`` denies a duplicate or
        a velocity breach, and denies retryably when the shared store is
        unavailable or the arguments cannot be canonicalized.
        """
        settings = get_settings()
        mode = settings.WALLET_REPLAN_GUARD
        if mode == ReplanGuardMode.OFF:
            return ReplanDecision(allowed=True)
        enforce = mode == ReplanGuardMode.ENFORCE
        try:
            return await self._check_and_reserve(
                settings=settings,
                enforce=enforce,
                wallet_id=wallet_id,
                tool_name=tool_name,
                arguments=arguments,
                owner=owner,
                credits=credits,
                allow_identical_repeats=allow_identical_repeats,
            )
        except (ReplanGuardUnavailable, CanonicalizationError) as exc:
            logger.warning(
                "replan_guard_unavailable mode=%s wallet_id=%s tool=%s error=%s",
                mode.value,
                wallet_id,
                tool_name,
                exc,
            )
        except Exception as exc:
            logger.exception(
                "replan_guard_unexpected_error mode=%s wallet_id=%s tool=%s (%s)",
                mode.value,
                wallet_id,
                tool_name,
                type(exc).__name__,
            )
        if enforce:
            return ReplanDecision(
                allowed=False,
                reason=REASON_UNAVAILABLE,
                details={"reason_code": REASON_UNAVAILABLE},
                retryable=True,
            )
        return ReplanDecision(allowed=True, would_deny_reason=REASON_UNAVAILABLE)

    async def _check_and_reserve(
        self,
        *,
        settings: Any,
        enforce: bool,
        wallet_id: str,
        tool_name: str,
        arguments: Any,
        owner: str,
        credits: Decimal,
        allow_identical_repeats: bool,
    ) -> ReplanDecision:
        digest = canonical_request_hash(
            tool_name, arguments, casefold_fields=settings.replan_casefold_fields
        )
        tag = _wallet_tag(wallet_id)
        velocity_window = int(settings.WALLET_VELOCITY_WINDOW_SECONDS)
        bucket = int(time.time() // velocity_window) * velocity_window
        req = _Request(
            dedup_key=f"amw:{{{tag}}}:dedup:{digest}",
            credits_key=f"amw:{{{tag}}}:vel:credits:{bucket}",
            calls_key=f"amw:{{{tag}}}:vel:calls:{bucket}",
            owner=_owner_token(owner),
            dedup_ttl_ms=int(settings.WALLET_DEDUP_WINDOW_SECONDS) * 1000,
            dedup_enabled=not allow_identical_repeats,
            cost_units=credits_to_minor_units(credits),
            credits_limit=credits_to_minor_units(settings.WALLET_VELOCITY_MAX_CREDITS),
            calls_limit=int(settings.WALLET_VELOCITY_MAX_CALLS),
            # Outlive the bucket so a late refund still finds its counter.
            velocity_ttl_ms=(velocity_window + 60) * 1000,
            force=not enforce,
        )
        client = await self._client()
        if client is None:
            backend = "memory"
            status, dedup_held, applied, credits_after, calls_after = (
                self._memory.acquire(req)
            )
        else:
            backend = "redis"
            try:
                raw = await client.eval(
                    _ACQUIRE_LUA,
                    3,
                    req.dedup_key,
                    req.credits_key,
                    req.calls_key,
                    req.owner,
                    req.dedup_ttl_ms,
                    1 if req.dedup_enabled else 0,
                    req.cost_units,
                    req.credits_limit,
                    req.calls_limit,
                    req.velocity_ttl_ms,
                    1 if req.force else 0,
                )
            except Exception as exc:
                await self._drop_client(client)
                raise ReplanGuardUnavailable("redis_eval_failed") from exc
            status = str(raw[0])
            dedup_held = int(raw[1]) == 1
            applied = int(raw[2]) == 1
            credits_after = int(raw[3])
            calls_after = int(raw[4])

        reservation = (
            ReplanReservation(
                backend=backend,
                dedup_key=req.dedup_key,
                credits_key=req.credits_key,
                calls_key=req.calls_key,
                owner=req.owner,
                dedup_held=dedup_held,
                velocity_applied=applied,
                cost_units=req.cost_units if applied else 0,
            )
            if dedup_held or applied
            else None
        )
        if status == _STATUS_OK:
            return ReplanDecision(allowed=True, reservation=reservation)

        if status == _STATUS_DUPLICATE:
            reason = REASON_DUPLICATE
            details: dict[str, Any] = {
                "reason_code": reason,
                "scope": "wallet",
                "window_seconds": int(settings.WALLET_DEDUP_WINDOW_SECONDS),
                "canonical_request_hash": digest,
            }
        else:
            reason = REASON_VELOCITY
            details = {
                "reason_code": reason,
                "scope": "wallet",
                "window_seconds": velocity_window,
            }
            if status == _STATUS_VELOCITY_CREDITS:
                details.update(
                    limit="credits",
                    limit_credits=str(settings.WALLET_VELOCITY_MAX_CREDITS),
                    window_credits=_minor_units_to_credits(
                        credits_after - (req.cost_units if applied else 0)
                    ),
                    requested_credits=_minor_units_to_credits(req.cost_units),
                )
            else:
                details.update(
                    limit="calls",
                    limit_calls=req.calls_limit,
                    window_calls=calls_after - (1 if applied else 0),
                )
        logger.warning(
            "replan_guard_%s mode=%s wallet_id=%s tool=%s request_hash_prefix=%s "
            "backend=%s",
            "deny" if enforce else "would_deny",
            "enforce" if enforce else "log_only",
            wallet_id,
            tool_name,
            digest[:16],
            backend,
            extra={"reason_code": reason},
        )
        if enforce:
            # Nothing was recorded on a denial (force is off), so there is
            # nothing to hand back.
            return ReplanDecision(allowed=False, reason=reason, details=details)
        return ReplanDecision(
            allowed=True,
            would_deny_reason=reason,
            details=details,
            reservation=reservation,
        )

    async def release(self, reservation: ReplanReservation | None) -> None:
        """Atomically drop the owner's lock and refund recorded velocity.

        Best effort and never raises: a refund the store cannot take leaves
        the lock to expire with its window, which only ever errs towards
        refusing a duplicate, never towards allowing one.
        """
        if reservation is None or not (
            reservation.dedup_held or reservation.velocity_applied
        ):
            return
        try:
            if reservation.backend == "memory":
                self._memory.release(reservation)
                return
            client = await self._client()
            if client is None:
                logger.warning(
                    "replan_guard_release_skipped: shared store not reachable"
                )
                return
            try:
                await client.eval(
                    _RELEASE_LUA,
                    3,
                    reservation.dedup_key,
                    reservation.credits_key,
                    reservation.calls_key,
                    reservation.owner,
                    1 if reservation.dedup_held else 0,
                    1 if reservation.velocity_applied else 0,
                    reservation.cost_units,
                )
            except Exception:
                await self._drop_client(client)
                raise
        except Exception as exc:
            logger.warning(
                "replan_guard_release_failed: lock and velocity stay recorded "
                "until the window expires (%s)",
                type(exc).__name__,
            )

    async def aclose(self) -> None:
        client = self._redis
        self._redis = None
        self._redis_url = None
        if client is not None:
            await self._close_quietly(client)


_guard: ReplanGuard | None = None


def get_replan_guard() -> ReplanGuard:
    global _guard
    if _guard is None:
        _guard = ReplanGuard()
    return _guard


def reset_replan_guard_for_tests() -> None:
    """Drop the singleton (and its per-process counters). Test hook."""
    global _guard
    _guard = None


__all__ = [
    "REASON_DUPLICATE",
    "REASON_UNAVAILABLE",
    "REASON_VELOCITY",
    "ReplanDecision",
    "ReplanGuard",
    "ReplanReservation",
    "credits_to_minor_units",
    "get_replan_guard",
    "reset_replan_guard_for_tests",
]
