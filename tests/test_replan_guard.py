"""Wallet re-plan guard: modes, dedup, velocity, atomic release.

The same behaviour is asserted on the per-process store and on a throwaway
local redis-server (the single Lua script), so the fallback cannot drift from
the shared implementation. Concurrency tests prove check-and-set is atomic:
of N simultaneous identical re-plans exactly one reserves.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.core.config import get_settings
from app.services import replan_guard as rg
from app.services.replan_guard import (
    REASON_DUPLICATE,
    REASON_UNAVAILABLE,
    REASON_VELOCITY,
    ReplanGuard,
    ReplanGuardUnavailable,
    credits_to_minor_units,
)

TOOL = "partner.notes.write"


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


@pytest.fixture(scope="module")
def redis_port():
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("redis-server binary is not installed")
    port = _free_port()
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--bind", "127.0.0.1", "--save", ""],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 15
    while time.time() < deadline and not _pong(port):
        time.sleep(0.05)
    if not _pong(port):
        proc.kill()
        pytest.skip("could not start a local redis-server")
    yield port
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(params=["memory", "redis"])
def backend(request, monkeypatch):
    if request.param == "redis":
        port = request.getfixturevalue("redis_port")
        monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{port}/0")
    else:
        monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    yield request.param
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def guard(backend, monkeypatch):
    monkeypatch.setenv("WALLET_REPLAN_GUARD", "enforce")
    monkeypatch.setenv("WALLET_VELOCITY_MAX_CREDITS", "0")
    monkeypatch.setenv("WALLET_VELOCITY_MAX_CALLS", "0")
    get_settings.cache_clear()
    g = ReplanGuard()
    yield g
    await g.aclose()
    get_settings.cache_clear()


def _mode(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()


async def _reserve(g, wallet, owner, args=None, credits="1", **kw):
    return await g.check_and_reserve(
        wallet_id=wallet,
        tool_name=TOOL,
        arguments={"note": "hello"} if args is None else args,
        owner=owner,
        credits=Decimal(credits),
        **kw,
    )


def _wallet() -> str:
    return f"wallet-{uuid.uuid4().hex[:12]}"


# ── dedup ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_new_key_identical_replan_is_denied_across_permits(guard):
    wallet = _wallet()
    first = await _reserve(guard, wallet, "key-1")
    assert first.allowed and first.reservation is not None
    # A fresh idempotency key (and, on /mcp, a fresh auto-minted permit --
    # the guard does not see permits at all) repeating the same arguments.
    second = await _reserve(guard, wallet, "key-2", args={"note": "hello"})
    assert not second.allowed
    assert second.reason == REASON_DUPLICATE
    assert second.details["scope"] == "wallet"
    assert second.reservation is None


@pytest.mark.anyio
async def test_reordered_and_renumbered_replan_is_still_a_duplicate(guard):
    wallet = _wallet()
    assert (await _reserve(guard, wallet, "k1", args={"a": 1, "b": "x"})).allowed
    again = await _reserve(guard, wallet, "k2", args={"b": "x", "a": 1.0})
    assert again.reason == REASON_DUPLICATE


@pytest.mark.anyio
async def test_same_key_reenters_its_own_lock(guard):
    wallet = _wallet()
    assert (await _reserve(guard, wallet, "key-1")).allowed
    again = await _reserve(guard, wallet, "key-1")
    assert again.allowed
    # Re-entry records no second velocity unit.
    assert again.reservation is not None
    assert again.reservation.velocity_applied is False


@pytest.mark.anyio
async def test_dedup_is_wallet_scoped_and_argument_scoped(guard):
    a, b = _wallet(), _wallet()
    assert (await _reserve(guard, a, "k1")).allowed
    assert (await _reserve(guard, b, "k2")).allowed
    assert (await _reserve(guard, a, "k3", args={"note": "other"})).allowed
    # Case is significant unless the field is configured for folding.
    assert (await _reserve(guard, a, "k4", args={"note": "HELLO"})).allowed


@pytest.mark.anyio
async def test_casefold_fields_are_configurable(guard, monkeypatch):
    _mode(monkeypatch, REPLAN_CASEFOLD_FIELDS="email")
    wallet = _wallet()
    assert (await _reserve(guard, wallet, "k1", args={"email": "A@X.io"})).allowed
    again = await _reserve(guard, wallet, "k2", args={"email": "a@x.io"})
    assert again.reason == REASON_DUPLICATE


@pytest.mark.anyio
async def test_allow_identical_repeats_skips_dedup_only(guard, monkeypatch):
    _mode(monkeypatch, WALLET_VELOCITY_MAX_CALLS=2)
    wallet = _wallet()
    for key in ("k1", "k2"):
        assert (
            await _reserve(guard, wallet, key, allow_identical_repeats=True)
        ).allowed
    third = await _reserve(guard, wallet, "k3", allow_identical_repeats=True)
    assert third.reason == REASON_VELOCITY


@pytest.mark.anyio
async def test_release_frees_the_lock_and_only_the_owners(guard):
    wallet = _wallet()
    first = await _reserve(guard, wallet, "k1")
    await guard.release(first.reservation)
    second = await _reserve(guard, wallet, "k2")
    assert second.allowed
    # Releasing the stale first reservation again must not free k2's lock.
    await guard.release(first.reservation)
    third = await _reserve(guard, wallet, "k3")
    assert third.reason == REASON_DUPLICATE


@pytest.mark.anyio
async def test_dedup_window_expires(guard, monkeypatch):
    _mode(monkeypatch, WALLET_DEDUP_WINDOW_SECONDS=1)
    wallet = _wallet()
    assert (await _reserve(guard, wallet, "k1")).allowed
    assert (await _reserve(guard, wallet, "k2")).reason == REASON_DUPLICATE
    await asyncio.sleep(1.2)
    assert (await _reserve(guard, wallet, "k3")).allowed


# ── velocity ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_velocity_credit_cap_counts_integer_minor_units(guard, monkeypatch):
    _mode(monkeypatch, WALLET_VELOCITY_MAX_CREDITS="0.3")
    wallet = _wallet()
    # 0.1 three times is exactly 0.3: float addition would overshoot.
    for i in range(3):
        decision = await _reserve(guard, wallet, f"k{i}", args={"i": i}, credits="0.1")
        assert decision.allowed, decision.details
    over = await _reserve(guard, wallet, "k9", args={"i": 9}, credits="0.00000001")
    assert over.reason == REASON_VELOCITY
    assert over.details["limit"] == "credits"
    assert over.details["window_credits"] == "0.3"
    assert over.details["requested_credits"] == "0.00000001"


@pytest.mark.anyio
async def test_velocity_call_cap_spans_all_permits(guard, monkeypatch):
    _mode(monkeypatch, WALLET_VELOCITY_MAX_CALLS=2)
    wallet = _wallet()
    assert (await _reserve(guard, wallet, "k1", args={"n": 1})).allowed
    assert (await _reserve(guard, wallet, "k2", args={"n": 2})).allowed
    over = await _reserve(guard, wallet, "k3", args={"n": 3})
    assert over.reason == REASON_VELOCITY
    assert over.details["limit"] == "calls"
    assert over.details["window_calls"] == 2
    # Another wallet has its own budget.
    assert (await _reserve(guard, _wallet(), "k4", args={"n": 3})).allowed


@pytest.mark.anyio
async def test_release_refunds_velocity_atomically_with_the_lock(guard, monkeypatch):
    _mode(monkeypatch, WALLET_VELOCITY_MAX_CREDITS="2")
    wallet = _wallet()
    first = await _reserve(guard, wallet, "k1", args={"n": 1}, credits="2")
    assert first.allowed
    blocked = await _reserve(guard, wallet, "k2", args={"n": 2}, credits="1")
    assert blocked.reason == REASON_VELOCITY
    await guard.release(first.reservation)
    # Both the credits and the lock came back.
    assert (await _reserve(guard, wallet, "k3", args={"n": 2}, credits="2")).allowed
    assert (await _reserve(guard, wallet, "k4", args={"n": 4}, credits="1")).reason == (
        REASON_VELOCITY
    )


@pytest.mark.anyio
async def test_release_never_drives_counters_negative(guard, monkeypatch):
    _mode(monkeypatch, WALLET_VELOCITY_MAX_CALLS=1)
    wallet = _wallet()
    first = await _reserve(guard, wallet, "k1", args={"n": 1})
    await guard.release(first.reservation)
    await guard.release(first.reservation)  # double release is a no-op
    assert (await _reserve(guard, wallet, "k2", args={"n": 2})).allowed
    assert (await _reserve(guard, wallet, "k3", args={"n": 3})).reason == (
        REASON_VELOCITY
    )


def test_minor_units_are_exact_integers():
    assert credits_to_minor_units(Decimal("1")) == 100_000_000
    assert credits_to_minor_units(Decimal("0.00000001")) == 1
    # Finer than storage precision rounds up: the cap leans tight.
    assert credits_to_minor_units(Decimal("0.000000001")) == 1
    assert credits_to_minor_units(Decimal("0")) == 0
    assert credits_to_minor_units(Decimal("-5")) == 0
    assert credits_to_minor_units(Decimal("1e30")) == 2**52


# ── modes ────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_log_only_never_blocks_but_still_records(guard, monkeypatch, caplog):
    _mode(monkeypatch, WALLET_REPLAN_GUARD="log_only", WALLET_VELOCITY_MAX_CALLS=1)
    wallet = _wallet()
    first = await _reserve(guard, wallet, "k1")
    assert first.allowed and first.would_deny_reason is None
    with caplog.at_level("WARNING", logger="app.services.replan_guard"):
        dup = await _reserve(guard, wallet, "k2")
    assert dup.allowed
    assert dup.would_deny_reason == REASON_DUPLICATE
    assert any("replan_guard_would_deny" in r.getMessage() for r in caplog.records)
    # The allowed duplicate still counted towards velocity (it will run).
    assert dup.reservation is not None and dup.reservation.velocity_applied
    assert dup.reservation.dedup_held is False  # never steals k1's lock


@pytest.mark.anyio
async def test_off_mode_records_nothing(guard, monkeypatch):
    _mode(monkeypatch, WALLET_REPLAN_GUARD="off")
    wallet = _wallet()
    for key in ("k1", "k2"):
        decision = await _reserve(guard, wallet, key)
        assert decision.allowed and decision.reservation is None
    _mode(monkeypatch, WALLET_REPLAN_GUARD="enforce")
    assert (await _reserve(guard, wallet, "k3")).allowed


def test_invalid_mode_is_rejected_at_startup(monkeypatch):
    monkeypatch.setenv("WALLET_REPLAN_GUARD", "enforced")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="WALLET_REPLAN_GUARD"):
        get_settings()
    monkeypatch.delenv("WALLET_REPLAN_GUARD")
    get_settings.cache_clear()
    assert get_settings().WALLET_REPLAN_GUARD.value == "log_only"


@pytest.mark.parametrize(
    "env",
    [
        {"WALLET_VELOCITY_MAX_CREDITS": "-1"},
        {"WALLET_VELOCITY_MAX_CREDITS": "100000000"},
        {"WALLET_VELOCITY_MAX_CALLS": "-1"},
        {"WALLET_DEDUP_WINDOW_SECONDS": "0"},
        {"WALLET_VELOCITY_WINDOW_SECONDS": "0"},
    ],
)
def test_out_of_range_settings_are_rejected(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match=next(iter(env))):
        get_settings()
    for key in env:
        monkeypatch.delenv(key)
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_store_outage_fails_closed_in_enforce_and_open_in_log_only(
    monkeypatch, caplog
):
    monkeypatch.setenv("REDIS_URL", "")
    g = ReplanGuard()

    async def down():
        raise ReplanGuardUnavailable("redis_unreachable")

    monkeypatch.setattr(g, "_client", down)
    _mode(monkeypatch, WALLET_REPLAN_GUARD="enforce")
    denied = await _reserve(g, _wallet(), "k1")
    assert not denied.allowed
    assert denied.reason == REASON_UNAVAILABLE and denied.retryable
    _mode(monkeypatch, WALLET_REPLAN_GUARD="log_only")
    allowed = await _reserve(g, _wallet(), "k1")
    assert allowed.allowed and allowed.would_deny_reason == REASON_UNAVAILABLE
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_log_only_never_blocks_on_unexpected_errors(monkeypatch):
    _mode(monkeypatch, WALLET_REPLAN_GUARD="log_only", REDIS_URL="")
    g = ReplanGuard()

    def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(rg, "canonical_request_hash", boom)
    assert (await _reserve(g, _wallet(), "k1")).allowed
    _mode(monkeypatch, WALLET_REPLAN_GUARD="enforce")
    denied = await _reserve(g, _wallet(), "k1")
    assert denied.reason == REASON_UNAVAILABLE
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_production_like_unreachable_redis_is_unavailable(monkeypatch):
    port = _free_port()  # nothing listening
    _mode(
        monkeypatch,
        REDIS_URL=f"redis://127.0.0.1:{port}/0",
        ENVIRONMENT="production",
        WALLET_REPLAN_GUARD="enforce",
    )
    g = ReplanGuard()
    denied = await _reserve(g, _wallet(), "k1")
    assert denied.reason == REASON_UNAVAILABLE
    _mode(monkeypatch, ENVIRONMENT="development")
    g2 = ReplanGuard()
    # Non-production falls back to per-process counters and still enforces.
    wallet = _wallet()
    assert (await _reserve(g2, wallet, "k1")).allowed
    assert (await _reserve(g2, wallet, "k2")).reason == REASON_DUPLICATE
    get_settings.cache_clear()


# ── atomicity and key layout ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_concurrent_identical_replans_reserve_exactly_once(guard):
    wallet = _wallet()
    results = await asyncio.gather(
        *(_reserve(guard, wallet, f"k{i}") for i in range(25))
    )
    assert sum(1 for r in results if r.allowed) == 1
    assert sum(1 for r in results if r.reason == REASON_DUPLICATE) == 24


@pytest.mark.anyio
async def test_concurrent_velocity_never_overshoots(guard, monkeypatch):
    _mode(monkeypatch, WALLET_VELOCITY_MAX_CALLS=5)
    wallet = _wallet()
    results = await asyncio.gather(
        *(_reserve(guard, wallet, f"k{i}", args={"i": i}) for i in range(30))
    )
    assert sum(1 for r in results if r.allowed) == 5


@pytest.mark.anyio
async def test_keys_share_one_cluster_hash_tag(guard):
    wallet = _wallet()
    decision = await _reserve(guard, wallet, "k1")
    res = decision.reservation
    assert res is not None
    tag = "{" + wallet + "}"
    for key in (res.dedup_key, res.credits_key, res.calls_key):
        assert key.startswith(f"amw:{tag}:")
    assert ":dedup:" in res.dedup_key and ":vel:" in res.credits_key


@pytest.mark.anyio
async def test_hostile_wallet_ids_cannot_break_the_hash_tag(guard):
    decision = await _reserve(guard, "a}b{c", "k1")
    res = decision.reservation
    assert res is not None
    tag = res.dedup_key.split(":")[1]
    assert tag.startswith("{h") and tag.endswith("}") and "}" not in tag[1:-1]


@pytest.mark.anyio
async def test_redis_keys_expire(guard, backend):
    if backend != "redis":
        pytest.skip("TTL is a Redis assertion")
    wallet = _wallet()
    decision = await _reserve(guard, wallet, "k1")
    client = await guard._client()
    res = decision.reservation
    assert await client.pttl(res.dedup_key) > 0
    assert await client.pttl(res.credits_key) > 0
    assert await client.pttl(res.calls_key) > 0
    # Velocity is stored as an exact integer of minor units.
    assert await client.get(res.credits_key) == str(100_000_000)
