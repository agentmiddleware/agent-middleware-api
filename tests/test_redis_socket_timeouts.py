"""Redis socket timeouts on the durable-state backend.

A hung Redis must not freeze requests or readiness: the client is built
with socket timeouts, and the health probe reports unhealthy promptly
instead of hanging.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.core import durable_state as durable_state_module
from app.core.config import get_settings
from app.core.durable_state import (
    DurableStateStore,
    reset_durable_state_for_tests,
)


class _FakeRedis:
    """Minimal stand-in for redis.asyncio.Redis."""

    def __init__(self) -> None:
        self.hang = False
        self.ping_calls = 0
        # Seeded hostile, as if REDIS_URL carried ?socket_timeout=999:
        # from_url keyword arguments alone would not dislodge these.
        self.connection_pool = SimpleNamespace(
            connection_kwargs={
                "socket_connect_timeout": 999,
                "socket_timeout": 999,
            }
        )

    async def ping(self):
        self.ping_calls += 1
        if self.hang:
            await asyncio.Event().wait()
        return True

    async def aclose(self):
        return None


@pytest.fixture
def redis_env(monkeypatch):
    """Point durable state at Redis with small, fast timeouts."""
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("STATE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SQLITE_URL", "")
    monkeypatch.setenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", "0.2")
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    yield
    get_settings.cache_clear()
    reset_durable_state_for_tests()


def _install_fake(monkeypatch, fake):
    captured: dict = {}

    def fake_from_url(url, **kwargs):
        captured.update(kwargs)
        captured["url"] = url
        return fake

    monkeypatch.setattr(durable_state_module.redis, "from_url", fake_from_url)
    return captured


async def test_redis_client_built_with_configured_timeouts(monkeypatch, redis_env):
    fake = _FakeRedis()
    captured = _install_fake(monkeypatch, fake)

    store = DurableStateStore()
    try:
        await store._ensure_ready()
        assert store.backend == "redis"
    finally:
        await store.close()

    assert captured["url"] == "redis://localhost:6379/0"
    assert captured["socket_connect_timeout"] == 0.2
    assert captured["socket_timeout"] == 0.2
    # The pool-level guard holds even when the URL query string (or the
    # fake's seed) names a larger bound.
    assert fake.connection_pool.connection_kwargs["socket_connect_timeout"] == 0.2
    assert fake.connection_pool.connection_kwargs["socket_timeout"] == 0.2


async def test_redis_health_report_unhealthy_on_hang(monkeypatch, redis_env):
    fake = _FakeRedis()
    _install_fake(monkeypatch, fake)

    store = DurableStateStore()
    try:
        await store._ensure_ready()
        assert store.backend == "redis"
        fake.hang = True

        start = time.monotonic()
        report = await store.health_report()
        elapsed = time.monotonic() - start
    finally:
        await store.close()

    assert report["ok"] is False
    assert report["backend"] == "redis"
    assert report["error"]
    assert elapsed < 2.0


async def test_redis_init_ping_bounded_on_hang(monkeypatch, redis_env):
    """A hang during first connect falls back to memory, it never wedges."""
    fake = _FakeRedis()
    fake.hang = True
    _install_fake(monkeypatch, fake)

    store = DurableStateStore()
    try:
        start = time.monotonic()
        await store._ensure_ready()
        elapsed = time.monotonic() - start
    finally:
        await store.close()

    assert elapsed < 2.0
    assert store.backend == "memory"


def test_redis_timeout_defaults_are_bounded(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    for var in (
        "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
        "REDIS_SOCKET_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS == 2.0
        assert settings.REDIS_SOCKET_TIMEOUT_SECONDS == 5.0
    finally:
        get_settings.cache_clear()
        reset_durable_state_for_tests()
