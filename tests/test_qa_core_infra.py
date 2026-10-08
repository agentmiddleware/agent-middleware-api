"""Deep QA for app/core infrastructure helpers and app/db value types.

Covers behavior with no direct tests today: credit storage bounds
(money movement), public-contact validation, product positioning copies,
the relative SQL decrement, retry/circuit-breaker semantics, DB URL
helpers, the naive-UTC bind type, runtime degradation flags, and
outbound-URL guard edges. Fast and deterministic: no sleeps, no network.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, Numeric, Table, create_engine, select, update
from sqlalchemy.exc import OperationalError

from app.core import url_guard
from app.core.config import get_settings
from app.core.credits import credit_amount_fits_storage
from app.core.db_urls import (
    as_asyncpg_url,
    as_sqlalchemy_url,
    is_postgres_url,
    is_sqlite_url,
    sqlite_path_from_url,
)
from app.core.product_positioning import (
    LEGACY_PRODUCT_LOOP,
    LEGACY_PRODUCT_WEDGE,
    get_product_positioning,
)
from app.core.public_contact import validated_public_contact
from app.core import resilience
from app.core.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    is_retryable_write_conflict,
    retry_with_backoff,
    run_with_write_conflict_retry,
)
from app.core.runtime_degradation import (
    get_runtime_degradation,
    mark_durable_state_fell_back,
    mark_rate_limiter_memory_fallback,
    reset_runtime_degradation,
)
from app.core.url_guard import check_outbound_url
from app.db.sql_expressions import clamped_decrement
from app.db.types import NaiveUTCDateTime


@pytest.fixture(autouse=True)
def _clean_shared_state():
    """Keep module-global flags and settings exactly as found."""
    reset_runtime_degradation()
    saved_allow_private = get_settings().ALLOW_PRIVATE_NETWORK_TARGETS
    yield
    reset_runtime_degradation()
    # Re-fetch: the settings cache may have been rebound while we ran.
    get_settings().ALLOW_PRIVATE_NETWORK_TARGETS = saved_allow_private


def _contact(**overrides):
    values = {
        "PUBLIC_CONTACT_NAME": "",
        "PUBLIC_CONTACT_EMAIL": "",
        "PUBLIC_CONTACT_URL": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# credits: money must never silently round through storage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["0", "0.00", "0.00000001", "0.1", "1", "100.50", "1E+3"],
)
def test_credit_amount_accepts_storable_values(raw):
    assert credit_amount_fits_storage(Decimal(raw)) is True


@pytest.mark.parametrize(
    "raw",
    [
        "1000000000000",  # at the cap, not below it
        "1000000000000.00",
        "999999999999.99999999",  # in range but float cannot hold 8dp there
        "-0.01",
        "0.123456789",  # 9 fractional digits do not survive Numeric(20, 8)
        "0.000000015",  # rounds at 8dp, so it is not stored as written
        "1.5E-9",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_credit_amount_rejects_unstorable_values(raw):
    assert credit_amount_fits_storage(Decimal(raw)) is False


def test_credit_amount_smallest_fractional_unit_fits():
    assert credit_amount_fits_storage(Decimal("0.00000001")) is True
    assert credit_amount_fits_storage(Decimal("0.000000001")) is False


# ---------------------------------------------------------------------------
# public_contact: fail closed on partial or provisional operator identity
# ---------------------------------------------------------------------------


def test_public_contact_absent_when_all_empty():
    assert validated_public_contact(_contact()) is None


def test_public_contact_accepts_complete_identity():
    contact = _contact(
        PUBLIC_CONTACT_NAME="Accountable Operator",
        PUBLIC_CONTACT_EMAIL="operator@designpartnerlabs.co",
        PUBLIC_CONTACT_URL="https://cal.example.net/pilot",
    )
    assert validated_public_contact(contact) == {
        "name": "Accountable Operator",
        "email": "operator@designpartnerlabs.co",
        "url": "https://cal.example.net/pilot",
    }


def test_public_contact_rejects_partial_identity():
    with pytest.raises(ValueError, match="together"):
        validated_public_contact(_contact(PUBLIC_CONTACT_NAME="Accountable Operator"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"PUBLIC_CONTACT_EMAIL": "not-an-email"},
        {"PUBLIC_CONTACT_EMAIL": "operator@example.com"},
        {"PUBLIC_CONTACT_EMAIL": "operator@company.invalid"},
        {"PUBLIC_CONTACT_URL": "http://cal.example.net/pilot"},
        {"PUBLIC_CONTACT_URL": "https://user:pass@cal.example.net/"},
        {"PUBLIC_CONTACT_NAME": "Te"},
        {"PUBLIC_CONTACT_NAME": "Test Operator"},
        {"PUBLIC_CONTACT_NAME": "Agent Middleware API"},
    ],
)
def test_public_contact_rejects_placeholders_and_bad_shapes(overrides):
    values = {
        "PUBLIC_CONTACT_NAME": "Accountable Operator",
        "PUBLIC_CONTACT_EMAIL": "operator@designpartnerlabs.co",
        "PUBLIC_CONTACT_URL": "https://cal.example.net/pilot",
    }
    values.update(overrides)
    contact = _contact(**values)
    with pytest.raises(ValueError):
        validated_public_contact(contact)


def test_public_contact_test_booking_host_message_names_the_host_problem():
    contact = _contact(
        PUBLIC_CONTACT_NAME="Accountable Operator",
        PUBLIC_CONTACT_EMAIL="operator@designpartnerlabs.co",
        PUBLIC_CONTACT_URL="https://www.thisisatest.tech/",
    )
    with pytest.raises(ValueError, match="test or placeholder"):
        validated_public_contact(contact)


# ---------------------------------------------------------------------------
# product_positioning: stable versioned copy for discovery clients
# ---------------------------------------------------------------------------


def test_product_positioning_returns_fresh_copy_each_call():
    first = get_product_positioning()
    first["semantics"].append("mutated")
    first["scope"]["transaction_state_machine"] = "mutated"
    second = get_product_positioning()
    assert "mutated" not in second["semantics"]
    assert second["scope"]["transaction_state_machine"] != "mutated"


def test_product_positioning_keeps_legacy_aliases():
    positioning = get_product_positioning()
    assert positioning["schema_version"] == "1.0"
    assert LEGACY_PRODUCT_WEDGE in positioning["legacy_aliases"]
    assert positioning["supersedes"] == ["product_wedge", "product_loop"]
    assert tuple(LEGACY_PRODUCT_LOOP) == (
        "discover",
        "authenticate",
        "authorize",
        "invoke",
        "meter",
        "receipt",
        "audit",
        "govern",
    )


# ---------------------------------------------------------------------------
# sql_expressions: relative decrement evaluated by the database
# ---------------------------------------------------------------------------


def test_clamped_decrement_clamps_at_zero_without_reading_first():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    wallets = Table(
        "wallets_probe",
        metadata,
        Column("wallet_id", Numeric, primary_key=True),
        Column("balance", Numeric(20, 8)),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            wallets.insert(),
            [
                {"wallet_id": 1, "balance": Decimal("10")},
                {"wallet_id": 2, "balance": Decimal("8")},
                {"wallet_id": 3, "balance": Decimal("2")},
            ],
        )
        conn.execute(
            update(wallets).values(
                balance=clamped_decrement(wallets.c.balance, Decimal("8"))
            )
        )
        rows = {
            row[0]: Decimal(str(row[1]))
            for row in conn.execute(
                select(wallets.c.wallet_id, wallets.c.balance).order_by(
                    wallets.c.wallet_id
                )
            )
        }
    assert rows == {1: Decimal("2"), 2: Decimal("0"), 3: Decimal("0")}
    engine.dispose()


# ---------------------------------------------------------------------------
# resilience: retry, circuit breaker, write-conflict restart
# ---------------------------------------------------------------------------


def _record_sleep(monkeypatch):
    calls: list[float] = []

    async def _sleep(delay: float) -> None:
        calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return calls


async def test_retry_with_backoff_returns_first_success_without_sleeping(
    monkeypatch,
):
    sleeps = _record_sleep(monkeypatch)
    calls = []

    @retry_with_backoff(max_attempts=3, base_delay=1.0)
    async def _op():
        calls.append(1)
        return "ok"

    assert await _op() == "ok"
    assert calls == [1]
    assert sleeps == []


async def test_retry_with_backoff_uses_exponential_delays(monkeypatch):
    sleeps = _record_sleep(monkeypatch)
    calls = []

    @retry_with_backoff(max_attempts=3, base_delay=1.0, exponential_base=2.0)
    async def _op():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")
        return "ok"

    assert await _op() == "ok"
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


async def test_retry_with_backoff_exhausts_and_reraises(monkeypatch):
    sleeps = _record_sleep(monkeypatch)
    calls = []

    @retry_with_backoff(
        max_attempts=3, base_delay=0.5, retriable_exceptions=(ConnectionError,)
    )
    async def _op():
        calls.append(1)
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        await _op()
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


async def test_retry_with_backoff_passes_through_cancelled_and_unexpected(
    monkeypatch,
):
    sleeps = _record_sleep(monkeypatch)

    @retry_with_backoff(max_attempts=3, base_delay=1.0)
    async def _cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _cancelled()

    calls = []

    @retry_with_backoff(max_attempts=3, retriable_exceptions=(ValueError,))
    async def _unexpected():
        calls.append(1)
        raise TypeError("not retriable")

    with pytest.raises(TypeError):
        await _unexpected()
    assert calls == [1]
    assert sleeps == []


def test_circuit_breaker_opens_half_opens_and_closes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(resilience.time, "monotonic", lambda: now[0])
    breaker = CircuitBreaker(
        failure_threshold=2, recovery_timeout=30.0, half_open_max_calls=1
    )
    assert breaker.state == CircuitBreaker.CLOSED
    breaker.record_failure()
    assert breaker.is_allowed() is True
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN
    assert breaker.is_allowed() is False

    now[0] += 31.0
    assert breaker.state == CircuitBreaker.HALF_OPEN
    assert breaker.is_allowed() is True
    breaker.record_success()
    assert breaker.state == CircuitBreaker.CLOSED
    assert breaker.is_allowed() is True


def test_circuit_breaker_half_open_failure_reopens(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(resilience.time, "monotonic", lambda: now[0])
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN
    now[0] += 31.0
    assert breaker.state == CircuitBreaker.HALF_OPEN
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN
    assert breaker.is_allowed() is False


async def test_circuit_breaker_call_counts_success_and_failure():
    breaker = CircuitBreaker(failure_threshold=2)

    async def _ok():
        return "fine"

    assert await breaker.call(_ok) == "fine"

    def _sync_ok():
        return 42

    assert await breaker.call(_sync_ok) == 42

    async def _boom():
        raise RuntimeError("backend down")

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    assert breaker.state == CircuitBreaker.OPEN

    calls = []

    async def _never():
        calls.append(1)

    with pytest.raises(CircuitBreakerOpen):
        await breaker.call(_never)
    assert calls == []


def _operational_error(message: str) -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(message))


@pytest.mark.parametrize(
    "message",
    ["database is locked", "DATABASE IS LOCKED", "SQLITE_BUSY_SNAPSHOT"],
)
def test_write_conflict_classifier_matches_transient_busy(message):
    assert is_retryable_write_conflict(_operational_error(message)) is True


@pytest.mark.parametrize(
    "message",
    ["no such table: wallets", "disk I/O error", "UNIQUE constraint failed"],
)
def test_write_conflict_classifier_rejects_substantive_faults(message):
    assert is_retryable_write_conflict(_operational_error(message)) is False


async def test_write_conflict_retry_restarts_transient_conflicts(monkeypatch):
    _record_sleep(monkeypatch)
    attempts = []

    async def _op():
        attempts.append(1)
        if len(attempts) < 3:
            raise _operational_error("database is locked")
        return "committed"

    result = await run_with_write_conflict_retry(
        _op, on_exhausted=lambda exc: RuntimeError("busy")
    )
    assert result == "committed"
    assert len(attempts) == 3


async def test_write_conflict_retry_raises_substantive_fault_at_once(
    monkeypatch,
):
    _record_sleep(monkeypatch)
    attempts = []

    async def _op():
        attempts.append(1)
        raise _operational_error("no such table: wallets")

    with pytest.raises(OperationalError):
        await run_with_write_conflict_retry(
            _op, on_exhausted=lambda exc: RuntimeError("busy")
        )
    assert len(attempts) == 1


async def test_write_conflict_retry_exhaustion_uses_caller_reason(monkeypatch):
    _record_sleep(monkeypatch)
    attempts = []

    async def _op():
        attempts.append(1)
        raise _operational_error("database is locked")

    class LedgerBusy(RuntimeError):
        pass

    with pytest.raises(LedgerBusy):
        await run_with_write_conflict_retry(
            _op, on_exhausted=lambda exc: LedgerBusy("ledger busy"), max_attempts=3
        )
    assert len(attempts) == 3


async def test_write_conflict_retry_honors_restart_predicate(monkeypatch):
    _record_sleep(monkeypatch)
    attempts = []

    async def _op():
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("stale snapshot read")
        return "recovered"

    result = await run_with_write_conflict_retry(
        _op,
        on_exhausted=lambda exc: RuntimeError("busy"),
        restart_on=lambda exc: isinstance(exc, ValueError),
        max_attempts=3,
    )
    assert result == "recovered"

    async def _other():
        raise KeyError("unrelated")

    with pytest.raises(KeyError):
        await run_with_write_conflict_retry(
            _other,
            on_exhausted=lambda exc: RuntimeError("busy"),
            restart_on=lambda exc: isinstance(exc, ValueError),
            max_attempts=3,
        )


# ---------------------------------------------------------------------------
# db_urls: scheme handling must not touch credentials or misroute backends
# ---------------------------------------------------------------------------


def test_db_url_scheme_matrix():
    assert is_postgres_url("postgresql://u:p@h/db") is True
    assert is_postgres_url("POSTGRESQL://U:P@H/DB") is True
    assert is_postgres_url("postgres://u:p@h/db") is True
    assert is_postgres_url("postgresql+asyncpg://u:p@h/db") is True
    assert is_postgres_url("  postgresql://u:p@h/db  ") is True
    assert is_postgres_url("sqlite+aiosqlite:///./x.db") is False
    assert is_postgres_url("") is False

    assert is_sqlite_url("sqlite:///./x.db") is True
    assert is_sqlite_url("SQLITE+AIOSQLITE:///./x.db") is True
    assert is_sqlite_url("sqlite+aiosqlite:///:memory:") is True
    assert is_sqlite_url("postgresql://u:p@h/db") is False
    assert is_sqlite_url("") is False


def test_db_url_converters_preserve_credentials_case():
    upper = "POSTGRESQL://Us3R:PaSsW0rd@Host/DB"
    assert as_asyncpg_url(upper) == "postgresql://Us3R:PaSsW0rd@Host/DB"
    assert as_sqlalchemy_url(upper) == "postgresql+asyncpg://Us3R:PaSsW0rd@Host/DB"
    assert as_sqlalchemy_url("  postgresql://u:p@h/db  ") == (
        "postgresql+asyncpg://u:p@h/db"
    )
    assert as_asyncpg_url("") == ""
    assert as_sqlalchemy_url("redis://localhost:6379/0") == ("redis://localhost:6379/0")


def test_sqlite_path_from_url_distinguishes_durable_from_ephemeral():
    assert sqlite_path_from_url("sqlite+aiosqlite:///./app.db") == "./app.db"
    assert sqlite_path_from_url("sqlite:////abs/app.db") == "/abs/app.db"
    assert sqlite_path_from_url("sqlite+aiosqlite:///:memory:") == ""
    assert sqlite_path_from_url("sqlite:///") == ""
    assert sqlite_path_from_url("postgresql://u:p@h/db") == ""
    # A durable filename that merely mentions memory stays durable.
    assert sqlite_path_from_url("sqlite:///./mode=memory.db") == "./mode=memory.db"
    # mode=memory as a file: URI query parameter is ephemeral.
    assert sqlite_path_from_url("sqlite:///file:memdb?mode=memory&cache=shared") == ""


# ---------------------------------------------------------------------------
# types: naive-UTC bind normalization
# ---------------------------------------------------------------------------


def test_naive_utc_bind_type_converts_aware_and_passes_naive_through():
    bind = NaiveUTCDateTime()
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    converted = bind.process_bind_param(aware, None)
    assert converted == datetime(2026, 1, 1, 17, 0)
    assert converted.tzinfo is None

    naive = datetime(2026, 1, 1, 17, 0)
    assert bind.process_bind_param(naive, None) is naive
    assert bind.process_bind_param(None, None) is None
    assert bind.process_result_value(naive, None) is naive


# ---------------------------------------------------------------------------
# runtime_degradation: fallbacks stay visible to operators
# ---------------------------------------------------------------------------


def test_runtime_degradation_snapshot_lifecycle():
    snapshot = get_runtime_degradation()
    assert snapshot["degraded"] is False
    assert snapshot["rate_limiter"]["using_memory_fallback"] is False
    assert snapshot["durable_state"]["fell_back_to_memory"] is False
    assert snapshot["durable_state"]["intended_backend"] is None

    mark_rate_limiter_memory_fallback()
    snapshot = get_runtime_degradation()
    assert snapshot["degraded"] is True
    assert snapshot["rate_limiter"]["using_memory_fallback"] is True
    assert snapshot["rate_limiter"]["backend"] == "memory"

    reset_runtime_degradation()
    mark_durable_state_fell_back("postgres")
    snapshot = get_runtime_degradation()
    assert snapshot["degraded"] is True
    assert snapshot["durable_state"] == {
        "fell_back_to_memory": True,
        "intended_backend": "postgres",
    }


# ---------------------------------------------------------------------------
# url_guard: extra edges around scheme, normalization, and the local flag
# ---------------------------------------------------------------------------


async def test_url_guard_blocks_case_variants_and_userinfo_targets():
    assert await check_outbound_url("HTTP://127.0.0.1/") == "private_address_blocked"
    assert await check_outbound_url("http://localhost./") == "private_host_blocked"
    assert await check_outbound_url("http://user:pass@10.0.0.1/") == (
        "private_address_blocked"
    )
    assert await check_outbound_url("http://foo.local/") == "private_host_blocked"
    assert await check_outbound_url("http:///path") == "missing_host"


async def test_url_guard_allows_public_host_with_pinned_dns(monkeypatch):
    async def _resolve(_host):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr(url_guard, "_resolve_host", _resolve)
    assert await check_outbound_url("https://example.com/x") is None


async def test_url_guard_private_flag_skips_address_checks_but_never_schemes():
    get_settings().ALLOW_PRIVATE_NETWORK_TARGETS = True
    assert await check_outbound_url("http://127.0.0.1:8000/admin") is None
    assert await check_outbound_url("file:///etc/passwd") == "scheme_not_allowed"
    assert await check_outbound_url("javascript:alert(1)") == "scheme_not_allowed"
