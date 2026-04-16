"""
Durable state backend abstraction for runtime service stores.

Priority order:
1) PostgreSQL (DATABASE_URL)
2) Redis (REDIS_URL)
3) In-memory fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
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

        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._backend: str = "memory"
        self._redis: redis.Redis | None = None
        self._pg_pool: asyncpg.Pool | None = None

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
        if self._state_backend == "memory":
            return "memory"

        # auto/default
        if self._database_url:
            return "postgres"
        if self._redis_url:
            return "redis"
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
                elif self._backend == "redis":
                    self._redis = redis.from_url(
                        self._redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                    )
                    await self._redis.ping()
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

        assert self._redis is not None
        await self._redis.delete(self._redis_key(key))
        return True

    async def health_report(self) -> dict[str, Any]:
        await self._ensure_ready()

        if self._backend == "memory":
            return {
                "ok": True,
                "backend": "memory",
                "enabled": False,
                "reason": "No DATABASE_URL/REDIS_URL configured",
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

        # Keep init state so this instance can re-initialize if needed.
        self._initialized = False
        self._backend = "memory"


@lru_cache()
def get_durable_state() -> DurableStateStore:
    return DurableStateStore()


async def close_durable_state() -> None:
    await get_durable_state().close()
