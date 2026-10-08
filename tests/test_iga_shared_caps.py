"""Shared (cross-process) enterprise IGA caps via the Redis durable store.

These tests run against a throwaway redis-server on 127.0.0.1 started for
this module, so they prove real cross-process durability: wiping the
process-local counters with reset_iga_counters() simulates a fresh process
(or a second replica), and any cap that still holds must have come from the
shared store. Concurrent consumption tests prove the atomic check-and-record.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

import app.core.oidc_iga as oidc_iga
from app.core.config import get_settings
from app.core.durable_state import (
    close_durable_state,
    get_durable_state,
    reset_durable_state_for_tests,
)
from app.core.oidc_iga import enforce_tool_call

TOOL = "synthetic.tool"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _pong(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
            sock.sendall(b"PING\r\n")
            return sock.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def _wait_pong(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _pong(port):
            return True
        time.sleep(0.05)
    return False


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def _start_server(binary: str) -> tuple[subprocess.Popen, int]:
    for _ in range(5):
        port = _free_port()
        proc = subprocess.Popen(
            [
                binary,
                "--port",
                str(port),
                "--bind",
                "127.0.0.1",
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        if _wait_pong(port):
            return proc, port
        _stop(proc)
    raise AssertionError("could not start a local redis-server")


@pytest.fixture(scope="module")
def iga_redis_server():
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("redis-server binary is not installed")
    proc, port = _start_server(binary)
    yield port
    _stop(proc)


async def _point_at_redis(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    await close_durable_state()
    monkeypatch.setenv("STATE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{port}/0?socket_timeout=5")
    get_settings.cache_clear()
    reset_durable_state_for_tests()


@pytest_asyncio.fixture(autouse=True)
async def _iga_shared_env(monkeypatch, iga_redis_server):
    oidc_iga.reset_iga_counters()
    await _point_at_redis(monkeypatch, iga_redis_server)
    yield
    try:
        client = await get_durable_state().shared_redis()
        if client is not None:
            await client.flushdb()
    except Exception:
        pass
    await close_durable_state()
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    oidc_iga.reset_iga_counters()


def _stub_grant(monkeypatch: pytest.MonkeyPatch, grant: oidc_iga.IGAGrant) -> None:
    import app.services.policies as policies

    monkeypatch.setattr(oidc_iga, "resolve_policy_grants", lambda p: [grant])

    async def _bundle(_policy_id: str) -> SimpleNamespace:
        return SimpleNamespace(is_active=True, allowed_tools=[TOOL])

    monkeypatch.setattr(policies, "get_policy_bundle", _bundle)


def _principal() -> oidc_iga.EnterprisePrincipal:
    return oidc_iga.EnterprisePrincipal(
        subject=f"qa-{uuid.uuid4().hex[:12]}",
        provider="okta",
        issuer="https://synthetic.invalid",
        groups=("operators",),
    )


async def test_shared_max_uses_holds_across_processes(monkeypatch):
    """max_uses=2 survives a counter wipe: the third call is still denied."""
    _stub_grant(
        monkeypatch, oidc_iga.IGAGrant("operators", "synthetic-policy", max_uses=2)
    )
    principal = _principal()

    assert (await enforce_tool_call(principal, TOOL)).allowed
    assert (await enforce_tool_call(principal, TOOL)).allowed

    # A fresh process (or replica) starts with empty local counters.
    oidc_iga.reset_iga_counters()

    third = await enforce_tool_call(principal, TOOL)
    assert not third.allowed
    assert third.reason == "iga_max_uses_exceeded"
    assert third.details == {"used": 2, "limit": 2}


async def test_shared_concurrent_consumption_respects_cap(monkeypatch):
    """20 concurrent calls against max_uses=5 allow exactly 5."""
    _stub_grant(
        monkeypatch, oidc_iga.IGAGrant("operators", "synthetic-policy", max_uses=5)
    )
    principal = _principal()

    results = await asyncio.gather(
        *[enforce_tool_call(principal, TOOL) for _ in range(20)]
    )
    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]
    assert len(allowed) == 5
    assert len(denied) == 15
    assert {r.reason for r in denied} == {"iga_max_uses_exceeded"}


async def test_shared_velocity_holds_across_processes(monkeypatch):
    """A 2-per-60s velocity cap survives a counter wipe."""
    _stub_grant(
        monkeypatch,
        oidc_iga.IGAGrant(
            "operators",
            "synthetic-policy",
            velocity_window_seconds=60,
            velocity_max_calls=2,
        ),
    )
    principal = _principal()

    assert (await enforce_tool_call(principal, TOOL)).allowed
    assert (await enforce_tool_call(principal, TOOL)).allowed

    oidc_iga.reset_iga_counters()

    third = await enforce_tool_call(principal, TOOL)
    assert not third.allowed
    assert third.reason == "iga_velocity_exceeded"
    assert third.details == {
        "window_seconds": 60,
        "calls_in_window": 2,
        "limit": 2,
    }


async def test_shared_concurrent_velocity_respects_cap(monkeypatch):
    """10 concurrent calls against 3-per-60s allow exactly 3."""
    _stub_grant(
        monkeypatch,
        oidc_iga.IGAGrant(
            "operators",
            "synthetic-policy",
            velocity_window_seconds=60,
            velocity_max_calls=3,
        ),
    )
    principal = _principal()

    results = await asyncio.gather(
        *[enforce_tool_call(principal, TOOL) for _ in range(10)]
    )
    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]
    assert len(allowed) == 3
    assert len(denied) == 7
    assert {r.reason for r in denied} == {"iga_velocity_exceeded"}


async def test_shared_release_returns_use_across_restart(monkeypatch):
    """A released use is spendable again, and the reuse is shared too."""
    _stub_grant(
        monkeypatch, oidc_iga.IGAGrant("operators", "synthetic-policy", max_uses=1)
    )
    principal = _principal()

    first = await enforce_tool_call(principal, TOOL)
    assert first.allowed
    assert first.reservation is not None and first.reservation.shared

    oidc_iga.reset_iga_counters()
    await oidc_iga.release_tool_use(
        principal,
        TOOL,
        group="operators",
        policy_id="synthetic-policy",
        reservation=first.reservation,
    )
    assert (await enforce_tool_call(principal, TOOL)).allowed

    # The post-release use was recorded in the shared store as well.
    oidc_iga.reset_iga_counters()
    third = await enforce_tool_call(principal, TOOL)
    assert not third.allowed
    assert third.reason == "iga_max_uses_exceeded"


async def test_local_counters_are_per_process_without_shared_store(monkeypatch):
    """Without Redis the documented fallback holds: a wipe renews the budget."""
    await close_durable_state()
    monkeypatch.setenv("STATE_BACKEND", "memory")
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    reset_durable_state_for_tests()
    _stub_grant(
        monkeypatch, oidc_iga.IGAGrant("operators", "synthetic-policy", max_uses=1)
    )
    principal = _principal()

    first = await enforce_tool_call(principal, TOOL)
    assert first.allowed
    assert first.reservation is not None and not first.reservation.shared
    assert not (await enforce_tool_call(principal, TOOL)).allowed

    oidc_iga.reset_iga_counters()
    assert (await enforce_tool_call(principal, TOOL)).allowed


async def test_shared_store_outage_fails_closed(monkeypatch):
    """A dead Redis denies capped calls; uncapped grants still allow."""
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("redis-server binary is not installed")
    proc, port = _start_server(binary)
    try:
        await _point_at_redis(monkeypatch, port)
        _stub_grant(
            monkeypatch,
            oidc_iga.IGAGrant("operators", "synthetic-policy", max_uses=5),
        )
        principal = _principal()
        assert (await enforce_tool_call(principal, TOOL)).allowed

        _stop(proc)
        denied = await enforce_tool_call(principal, TOOL)
        assert not denied.allowed
        assert denied.reason == "iga_cap_store_unavailable"

        _stub_grant(monkeypatch, oidc_iga.IGAGrant("operators", "synthetic-policy"))
        assert (await enforce_tool_call(principal, TOOL)).allowed
    finally:
        _stop(proc)
