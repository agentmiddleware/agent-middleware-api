"""
Durable state backend abstraction for runtime service stores.

Priority order:
1) PostgreSQL (DATABASE_URL)
2) Redis (REDIS_URL)
3) SQLite (SQLITE_URL)
4) In-memory fallback
"""

from __future__ import annotations

import aiosqlite
import asyncio
import json
import logging
import time as _time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Any

import asyncpg
import redis.asyncio as redis

from .config import get_settings

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)  # type: ignore[arg-type]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class DurableStateStore:
    """Simple key/value JSON state store backed by PostgreSQL or Redis."""

    def __init__(self):
        settings = get_settings()
        self.namespace = settings.STATE_NAMESPACE
        self._state_backend = settings.STATE_BACKEND.strip().lower()
        self._redis_url = settings.REDIS_URL.strip()
        self._database_url = settings.DATABASE_URL.strip()
        self._sqlite_url = settings.SQLITE_URL.strip()

        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._backend: str = "memory"
        self._redis: redis.Redis | None = None
        self._pg_pool: asyncpg.Pool | None = None
        self._sqlite_conn: aiosqlite.Connection | None = None

        # In-process nonce map for the memory backend (single-worker / tests).
        # Maps nonce key -> monotonic expiry timestamp.
        self._nonce_mem: dict[str, float] = {}
        self._nonce_lock = asyncio.Lock()

        # In-process budget map for the memory backend: key -> (spent, expiry).
        self._budget_mem: dict[str, tuple[float, float]] = {}
        self._budget_lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def enabled(self) -> bool:
        return self._backend != "memory"

    def _resolve_backend(self) -> str:
        if self._state_backend in ("postgres", "postgresql"):
            return "postgres" if self._database_url else "memory"
        if self._state_backend == "redis":
            return "redis" if self._redis_url else "memory"
        if self._state_backend == "sqlite":
            return "sqlite" if self._sqlite_url else "memory"
        if self._state_backend == "memory":
            return "memory"

        # auto/default
        if self._database_url:
            return "postgres"
        if self._redis_url:
            return "redis"
        if self._sqlite_url:
            return "sqlite"
        return "memory"

    async def _ensure_ready(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            self._backend = self._resolve_backend()

            try:
                if self._backend == "postgres":
                    self._pg_pool = await asyncpg.create_pool(
                        self._database_url,
                        min_size=1,
                        max_size=5,
                        timeout=10,
                    )
                    async with self._pg_pool.acquire() as conn:
                        await conn.execute(
                            """
                            CREATE TABLE IF NOT EXISTS app_state_kv (
                                namespace TEXT NOT NULL,
                                state_key TEXT NOT NULL,
                                payload JSONB NOT NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                PRIMARY KEY(namespace, state_key)
                            )
                            """
                        )
                        await conn.execute(
                            """
                            CREATE TABLE IF NOT EXISTS app_idempotency (
                                namespace TEXT NOT NULL,
                                nonce_key TEXT NOT NULL,
                                expires_at TIMESTAMPTZ NOT NULL,
                                PRIMARY KEY(namespace, nonce_key)
                            )
                            """
                        )
                        await conn.execute(
                            """
                            CREATE TABLE IF NOT EXISTS app_budget (
                                namespace TEXT NOT NULL,
                                budget_key TEXT NOT NULL,
                                spent DOUBLE PRECISION NOT NULL DEFAULT 0,
                                expires_at TIMESTAMPTZ NOT NULL,
                                PRIMARY KEY(namespace, budget_key)
                            )
                            """
                        )
                elif self._backend == "redis":
                    self._redis = redis.from_url(
                        self._redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                    )
                    await self._redis.ping()
                elif self._backend == "sqlite":
                    self._sqlite_conn = await aiosqlite.connect(self._sqlite_url)
                    self._sqlite_conn.row_factory = aiosqlite.Row
                    await self._sqlite_conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS app_state_kv (
                            namespace TEXT NOT NULL,
                            state_key TEXT NOT NULL,
                            payload TEXT NOT NULL,
                            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                            PRIMARY KEY(namespace, state_key)
                        )
                        """
                    )
                    await self._sqlite_conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS app_idempotency (
                            namespace TEXT NOT NULL,
                            nonce_key TEXT NOT NULL,
                            expires_at REAL NOT NULL,
                            PRIMARY KEY(namespace, nonce_key)
                        )
                        """
                    )
                    await self._sqlite_conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS app_budget (
                            namespace TEXT NOT NULL,
                            budget_key TEXT NOT NULL,
                            spent REAL NOT NULL DEFAULT 0,
                            expires_at REAL NOT NULL,
                            PRIMARY KEY(namespace, budget_key)
                        )
                        """
                    )
                    await self._sqlite_conn.commit()
            except Exception:
                logger.exception(
                    "Failed to initialize durable state backend '%s'; falling "
                    "back to in-memory.",
                    self._backend,
                )
                await self.close()
                self._backend = "memory"

            self._initialized = True

    def _redis_key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def load_json(self, key: str) -> Any | None:
        await self._ensure_ready()
        if self._backend == "memory":
            return None

        if self._backend == "postgres":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT payload FROM app_state_kv WHERE namespace = $1 "
                    "AND state_key = $2",
                    self.namespace,
                    key,
                )
            if not row:
                return None
            payload = row["payload"]
            if isinstance(payload, str):
                return json.loads(payload)
            return payload

        if self._backend == "sqlite":
            assert self._sqlite_conn is not None
            async with self._sqlite_conn.execute(
                "SELECT payload FROM app_state_kv WHERE namespace = ? AND state_key = ?",
                (self.namespace, key),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return json.loads(row["payload"])

        assert self._redis is not None
        raw = await self._redis.get(self._redis_key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def save_json(self, key: str, value: Any) -> bool:
        await self._ensure_ready()
        if self._backend == "memory":
            return False

        encoded = json.dumps(value, default=_json_default)

        if self._backend == "postgres":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO app_state_kv (namespace, state_key, payload, updated_at)
                    VALUES ($1, $2, $3::jsonb, NOW())
                    ON CONFLICT (namespace, state_key)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                    """,
                    self.namespace,
                    key,
                    encoded,
                )
            return True

        if self._backend == "sqlite":
            assert self._sqlite_conn is not None
            await self._sqlite_conn.execute(
                """
                INSERT INTO app_state_kv (namespace, state_key, payload, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(namespace, state_key)
                DO UPDATE SET payload = excluded.payload, updated_at = datetime('now')
                """,
                (self.namespace, key, encoded),
            )
            await self._sqlite_conn.commit()
            return True

        assert self._redis is not None
        await self._redis.set(self._redis_key(key), encoded)
        return True

    async def delete(self, key: str) -> bool:
        await self._ensure_ready()
        if self._backend == "memory":
            return False

        if self._backend == "postgres":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM app_state_kv WHERE namespace = $1 AND state_key = $2",
                    self.namespace,
                    key,
                )
            return True

        if self._backend == "sqlite":
            assert self._sqlite_conn is not None
            await self._sqlite_conn.execute(
                "DELETE FROM app_state_kv WHERE namespace = ? AND state_key = ?",
                (self.namespace, key),
            )
            await self._sqlite_conn.commit()
            return True

        assert self._redis is not None
        await self._redis.delete(self._redis_key(key))
        return True

    async def list_keys(self, prefix: str) -> list[str]:
        """List durable state keys by prefix for row-keyed service state."""
        await self._ensure_ready()
        if self._backend == "memory":
            return []

        if self._backend == "postgres":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT state_key
                    FROM app_state_kv
                    WHERE namespace = $1 AND state_key LIKE $2
                    ORDER BY state_key
                    """,
                    self.namespace,
                    f"{prefix}%",
                )
            return [row["state_key"] for row in rows]

        if self._backend == "sqlite":
            assert self._sqlite_conn is not None
            async with self._sqlite_conn.execute(
                """
                SELECT state_key
                FROM app_state_kv
                WHERE namespace = ? AND state_key LIKE ?
                ORDER BY state_key
                """,
                (self.namespace, f"{prefix}%"),
            ) as cursor:
                rows = await cursor.fetchall()
            return [row["state_key"] for row in rows]

        assert self._redis is not None
        keys: list[str] = []
        redis_prefix = self._redis_key(prefix)
        async for key in self._redis.scan_iter(match=f"{redis_prefix}*"):
            if key.startswith(f"{self.namespace}:"):
                keys.append(key.split(":", 1)[1])
        return sorted(keys)

    async def claim_once(self, key: str, ttl_seconds: int) -> bool:
        """
        Atomically claim a nonce / idempotency key for the first time.

        Returns True if the key was newly claimed (the caller may proceed) or
        False if it was already claimed within its TTL (a replay).

        The claim is backed by the configured durable backend, so it holds
        across workers when Postgres/Redis/SQLite is configured. With the
        in-memory backend the claim is per-process only.
        """
        await self._ensure_ready()
        ttl = max(1, int(ttl_seconds))

        if self._backend == "postgres":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    WITH expired AS (
                        DELETE FROM app_idempotency
                        WHERE namespace = $1 AND nonce_key = $2
                          AND expires_at < NOW()
                    )
                    INSERT INTO app_idempotency (namespace, nonce_key, expires_at)
                    VALUES ($1, $2, NOW() + make_interval(secs => $3))
                    ON CONFLICT (namespace, nonce_key) DO NOTHING
                    RETURNING nonce_key
                    """,
                    self.namespace,
                    key,
                    ttl,
                )
            return row is not None

        if self._backend == "sqlite":
            assert self._sqlite_conn is not None
            now = _time.time()
            await self._sqlite_conn.execute(
                "DELETE FROM app_idempotency WHERE namespace = ? "
                "AND nonce_key = ? AND expires_at < ?",
                (self.namespace, key, now),
            )
            cursor = await self._sqlite_conn.execute(
                "INSERT OR IGNORE INTO app_idempotency "
                "(namespace, nonce_key, expires_at) VALUES (?, ?, ?)",
                (self.namespace, key, now + ttl),
            )
            await self._sqlite_conn.commit()
            return cursor.rowcount == 1

        if self._backend == "redis":
            assert self._redis is not None
            was_set = await self._redis.set(
                self._redis_key(f"nonce:{key}"), "1", nx=True, ex=ttl
            )
            return bool(was_set)

        # memory backend: per-process claim map with lazy expiry purge.
        now = _time.time()
        async with self._nonce_lock:
            if len(self._nonce_mem) > 10_000:
                self._nonce_mem = {
                    k: exp for k, exp in self._nonce_mem.items() if exp > now
                }
            existing = self._nonce_mem.get(key)
            if existing is not None and existing > now:
                return False
            self._nonce_mem[key] = now + ttl
            return True

    async def consume_budget(
        self, key: str, amount: float, cap: float, ttl_seconds: int
    ) -> tuple[bool, float]:
        """
        Atomically add ``amount`` to a running total under ``key`` only if the
        new total stays within ``cap``. Returns ``(allowed, total_after)``; on
        rejection the stored total is left unchanged.

        Backed by the durable backend so a spend allowance holds across workers
        when Postgres/Redis/SQLite is configured.
        """
        await self._ensure_ready()
        amount = float(amount)
        cap = float(cap)
        ttl = max(1, int(ttl_seconds))

        if amount <= 0:
            return True, 0.0
        if amount > cap:
            return False, 0.0

        if self._backend == "postgres":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM app_budget WHERE namespace = $1 "
                        "AND budget_key = $2 AND expires_at < NOW()",
                        self.namespace,
                        key,
                    )
                    row = await conn.fetchrow(
                        """
                        INSERT INTO app_budget
                            (namespace, budget_key, spent, expires_at)
                        VALUES ($1, $2, $3, NOW() + make_interval(secs => $4))
                        ON CONFLICT (namespace, budget_key) DO UPDATE
                            SET spent = app_budget.spent + $3
                            WHERE app_budget.spent + $3 <= $5
                        RETURNING spent
                        """,
                        self.namespace,
                        key,
                        amount,
                        ttl,
                        cap,
                    )
            if row is not None:
                return True, float(row["spent"])
            return False, cap

        if self._backend == "sqlite":
            assert self._sqlite_conn is not None
            now = _time.time()
            await self._sqlite_conn.execute(
                "DELETE FROM app_budget WHERE namespace = ? AND budget_key = ? "
                "AND expires_at < ?",
                (self.namespace, key, now),
            )
            async with self._sqlite_conn.execute(
                "SELECT spent FROM app_budget WHERE namespace = ? AND budget_key = ?",
                (self.namespace, key),
            ) as cursor:
                existing = await cursor.fetchone()
            current = float(existing["spent"]) if existing else 0.0
            if current + amount > cap:
                await self._sqlite_conn.commit()
                return False, current
            new_total = current + amount
            await self._sqlite_conn.execute(
                """
                INSERT INTO app_budget (namespace, budget_key, spent, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, budget_key)
                DO UPDATE SET spent = ?
                """,
                (self.namespace, key, new_total, now + ttl, new_total),
            )
            await self._sqlite_conn.commit()
            return True, new_total

        if self._backend == "redis":
            assert self._redis is not None
            redis_key = self._redis_key(f"budget:{key}")
            new_total = float(await self._redis.incrbyfloat(redis_key, amount))
            if new_total == amount:
                await self._redis.expire(redis_key, ttl)
            if new_total > cap:
                await self._redis.incrbyfloat(redis_key, -amount)
                return False, new_total - amount
            return True, new_total

        # memory backend
        now = _time.time()
        async with self._budget_lock:
            spent, expiry = self._budget_mem.get(key, (0.0, 0.0))
            if expiry and expiry <= now:
                spent = 0.0
            if spent + amount > cap:
                return False, spent
            new_total = spent + amount
            self._budget_mem[key] = (new_total, now + ttl)
            return True, new_total

    async def health_report(self) -> dict[str, Any]:
        await self._ensure_ready()

        if self._backend == "memory":
            return {
                "ok": True,
                "backend": "memory",
                "enabled": False,
                "reason": "No DATABASE_URL/REDIS_URL/SQLITE_URL configured",
            }

        if self._backend == "postgres":
            try:
                assert self._pg_pool is not None
                async with self._pg_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                return {"ok": True, "backend": "postgres", "enabled": True}
            except Exception as exc:
                return {
                    "ok": False,
                    "backend": "postgres",
                    "enabled": True,
                    "error": str(exc),
                }

        if self._backend == "sqlite":
            try:
                assert self._sqlite_conn is not None
                await self._sqlite_conn.execute("SELECT 1")
                return {"ok": True, "backend": "sqlite", "enabled": True}
            except Exception as exc:
                return {
                    "ok": False,
                    "backend": "sqlite",
                    "enabled": True,
                    "error": str(exc),
                }

        try:
            assert self._redis is not None
            await self._redis.ping()
            return {"ok": True, "backend": "redis", "enabled": True}
        except Exception as exc:
            return {
                "ok": False,
                "backend": "redis",
                "enabled": True,
                "error": str(exc),
            }

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                logger.debug("Failed to close Redis client cleanly", exc_info=True)
            self._redis = None

        if self._pg_pool is not None:
            try:
                await self._pg_pool.close()
            except Exception:
                logger.debug("Failed to close Postgres pool cleanly", exc_info=True)
            self._pg_pool = None

        if self._sqlite_conn is not None:
            try:
                await self._sqlite_conn.close()
            except Exception:
                logger.debug("Failed to close SQLite connection cleanly", exc_info=True)
            self._sqlite_conn = None

        # Keep init state so this instance can re-initialize if needed.
        self._initialized = False
        self._backend = "memory"


@lru_cache()
def get_durable_state() -> DurableStateStore:
    return DurableStateStore()


async def close_durable_state() -> None:
    await get_durable_state().close()
