"""SEL-330: stuck-work sweep alerts without moving state, money, or budget.

Lease columns are not cleared. ``claim_due_calls`` already treats
``reconcile_lease_expires_at IS NULL OR reconcile_lease_expires_at <= now``
as free, and the guarded UPDATE re-checks that predicate, so a crashed
worker's leftover owner does not block the next sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import sqlite as sqlite_dialect

from app.core.config import ReplanGuardMode, get_settings
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    SigningKeyModel,
    WalletModel,
)
from app.services.stuck_work_sweep import run_stuck_work_sweep
from app.services.upstream_reconcile import DeliveryUncertainReconcileWorker

NOW = datetime(2026, 10, 20, 12, 0, 0)
AGE = 3600
GRACE = 300


def test_stuck_work_defaults_leave_existing_switches_alone() -> None:
    settings = get_settings()
    assert settings.STUCK_WORK_SWEEP_ENABLED is True
    assert settings.STUCK_WORK_UNCERTAIN_ALERT_AGE_SECONDS == 3600
    assert settings.STUCK_WORK_LEASE_GRACE_SECONDS == 300
    assert settings.STUCK_WORK_LEASE_REAPER_ENABLED is True
    assert settings.RETRY_LOOP_ALERT_ENABLED is False
    assert settings.WALLET_REPLAN_GUARD == ReplanGuardMode.LOG_ONLY
    assert settings.UPSTREAM_RECONCILE_WORKER_ENABLED is False
    assert settings.UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED is False


def test_claim_treats_expired_lease_as_free() -> None:
    worker = DeliveryUncertainReconcileWorker(
        None, quiescence_seconds=0, backoff_seconds=[30]
    )
    sql = str(
        worker.claim_statement(datetime(2026, 1, 1)).compile(
            dialect=sqlite_dialect.dialect()
        )
    )
    assert "reconcile_lease_expires_at IS NULL" in sql
    assert "reconcile_lease_expires_at <=" in sql


async def _wallet(wallet_id: str, balance: str = "100") -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            WalletModel(
                wallet_id=wallet_id,
                wallet_type="agent",
                balance=Decimal(balance),
            )
        )
        await session.commit()


async def _permit(permit_id: str, wallet_id: str, spent: str = "0") -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            SigningKeyModel(key_id=f"key-{permit_id}", public_key_b64="synthetic")
        )
        await session.flush()
        session.add(
            PermitModel(
                permit_id=permit_id,
                issuer_wallet_id=wallet_id,
                subject_wallet_id=wallet_id,
                scopes_json="[]",
                allowed_tools_json="[]",
                max_credits=Decimal("10"),
                spent_credits=Decimal(spent),
                expires_at=NOW + timedelta(days=1),
                nonce=f"nonce-{permit_id}",
                signature="synthetic",
                key_id=f"key-{permit_id}",
            )
        )
        await session.commit()


async def _ledger(entry_id: str, wallet_id: str, amount: str = "-2") -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            LedgerEntryModel(
                entry_id=entry_id,
                wallet_id=wallet_id,
                action="debit",
                amount=Decimal(amount),
                balance_after=Decimal("98"),
                operation_key=entry_id,
            )
        )
        await session.commit()


async def _record(
    record_id: str,
    wallet_id: str,
    *,
    created_at: datetime,
    ledger_entry_id: str | None = None,
    response_json: str | None = None,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            IdempotencyRecordModel(
                record_id=record_id,
                wallet_id=wallet_id,
                endpoint="/mcp/invoke",
                idempotency_key=record_id,
                request_hash="ab" * 32,
                ledger_entry_id=ledger_entry_id,
                response_json=response_json,
                created_at=created_at,
            )
        )
        await session.commit()


async def _attempt(
    attempt_id: str,
    record_id: str,
    wallet_id: str,
    permit_id: str,
    *,
    parked_at: datetime,
    state: str = "delivery_uncertain",
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    ledger_entry_id: str | None = None,
    credits_charged: str = "2",
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            McpDispatchAttemptModel(
                attempt_id=attempt_id,
                idempotency_record_id=record_id,
                wallet_id=wallet_id,
                permit_id=permit_id,
                public_tool_id="partner.notes.write",
                upstream_tool_name="notes.write",
                upstream_origin="https://upstream.example",
                request_hash="cd" * 32,
                ledger_entry_id=ledger_entry_id,
                credits_authorized=Decimal("2"),
                credits_charged=Decimal(credits_charged),
                state=state,
                completed_at=parked_at,
                updated_at=parked_at,
                dispatched_at=parked_at,
                reconcile_lease_owner=lease_owner,
                reconcile_lease_expires_at=lease_expires_at,
            )
        )
        await session.commit()


async def _snapshot(attempt_id: str, permit_id: str, wallet_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        attempt = await session.get(McpDispatchAttemptModel, attempt_id)
        permit = await session.get(PermitModel, permit_id)
        wallet = await session.get(WalletModel, wallet_id)
        ledger_count = await session.scalar(
            select(func.count()).select_from(LedgerEntryModel)
        )
        assert attempt is not None and permit is not None and wallet is not None
        return {
            "state": attempt.state,
            "reconcile_status": attempt.reconcile_status,
            "credits_charged": attempt.credits_charged,
            "debit_refunded_at": attempt.debit_refunded_at,
            "budget_released_at": attempt.budget_released_at,
            "lease_owner": attempt.reconcile_lease_owner,
            "lease_expires_at": attempt.reconcile_lease_expires_at,
            "spent_credits": permit.spent_credits,
            "balance": wallet.balance,
            "ledger_count": int(ledger_count or 0),
        }


@pytest.mark.anyio
async def test_aged_delivery_uncertain_alerts_with_buckets(
    clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    await _wallet("w-aged")
    await _permit("p-aged", "w-aged", spent="2")
    await _ledger("led-aged", "w-aged")
    await _record(
        "rec-aged",
        "w-aged",
        created_at=NOW - timedelta(seconds=AGE + 400),
        ledger_entry_id="led-aged",
    )
    await _attempt(
        "att-aged",
        "rec-aged",
        "w-aged",
        "p-aged",
        parked_at=NOW - timedelta(seconds=AGE + 400),
        ledger_entry_id="led-aged",
    )
    await _record(
        "rec-fresh",
        "w-aged",
        created_at=NOW - timedelta(seconds=30),
    )
    await _attempt(
        "att-fresh",
        "rec-fresh",
        "w-aged",
        "p-aged",
        parked_at=NOW - timedelta(seconds=30),
        credits_charged="0",
    )
    before = await _snapshot("att-aged", "p-aged", "w-aged")

    with caplog.at_level("WARNING", logger="app.services.stuck_work_sweep"):
        result = await run_stuck_work_sweep(now=NOW)

    alerts = [r for r in caplog.records if r.message == "stuck_work_alert"]
    assert len(alerts) == 1
    assert result.delivery_uncertain_aged == 1
    assert result.idempotency_needs_review == 0
    assert result.delivery_uncertain_oldest_age_seconds == AGE + 400
    assert result.delivery_uncertain_buckets == {"ge_1x": 1, "ge_6x": 0, "ge_24x": 0}
    assert alerts[0].delivery_uncertain_aged == 1
    assert alerts[0].delivery_uncertain_buckets == {
        "ge_1x": 1,
        "ge_6x": 0,
        "ge_24x": 0,
    }
    assert alerts[0].leases_cleared == 0
    assert await _snapshot("att-aged", "p-aged", "w-aged") == before


@pytest.mark.anyio
async def test_fresh_delivery_uncertain_does_not_alert(
    clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    await _wallet("w-fresh")
    await _permit("p-fresh", "w-fresh")
    await _record("rec-fresh-only", "w-fresh", created_at=NOW - timedelta(seconds=10))
    await _attempt(
        "att-fresh-only",
        "rec-fresh-only",
        "w-fresh",
        "p-fresh",
        parked_at=NOW - timedelta(seconds=10),
        credits_charged="0",
    )

    with caplog.at_level("WARNING", logger="app.services.stuck_work_sweep"):
        result = await run_stuck_work_sweep(now=NOW)

    assert result.delivery_uncertain_aged == 0
    assert [r for r in caplog.records if r.message == "stuck_work_alert"] == []


@pytest.mark.anyio
async def test_expired_lease_is_alerted_and_not_cleared(
    clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    """Past-grace leases stay set. Claim can already take them."""
    await _wallet("w-lease")
    await _permit("p-lease", "w-lease", spent="2")
    await _record("rec-expired", "w-lease", created_at=NOW - timedelta(hours=2))
    expired_at = NOW - timedelta(seconds=GRACE + 50)
    await _attempt(
        "att-expired",
        "rec-expired",
        "w-lease",
        "p-lease",
        parked_at=NOW - timedelta(seconds=30),
        lease_owner="crashed-worker",
        lease_expires_at=expired_at,
        credits_charged="2",
    )
    await _record("rec-live", "w-lease", created_at=NOW - timedelta(seconds=20))
    live_until = NOW + timedelta(seconds=120)
    await _attempt(
        "att-live",
        "rec-live",
        "w-lease",
        "p-lease",
        parked_at=NOW - timedelta(seconds=20),
        lease_owner="live-worker",
        lease_expires_at=live_until,
        credits_charged="0",
    )
    before_expired = await _snapshot("att-expired", "p-lease", "w-lease")
    before_live = await _snapshot("att-live", "p-lease", "w-lease")

    with caplog.at_level("WARNING", logger="app.services.stuck_work_sweep"):
        result = await run_stuck_work_sweep(now=NOW)

    assert result.expired_lease_count == 1
    assert result.delivery_uncertain_aged == 0
    assert result.leases_cleared == 0
    alerts = [r for r in caplog.records if r.message == "stuck_work_alert"]
    assert len(alerts) == 1
    assert alerts[0].expired_lease_count == 1
    assert alerts[0].lease_reaper == "alert_only"
    after_expired = await _snapshot("att-expired", "p-lease", "w-lease")
    after_live = await _snapshot("att-live", "p-lease", "w-lease")
    assert after_expired["lease_owner"] == "crashed-worker"
    assert after_expired["lease_expires_at"] == expired_at
    assert after_expired["state"] == "delivery_uncertain"
    assert after_live["lease_owner"] == "live-worker"
    assert after_live["lease_expires_at"] == live_until
    assert after_expired["spent_credits"] == before_expired["spent_credits"]
    assert after_expired["balance"] == before_expired["balance"]
    assert after_live == before_live


@pytest.mark.anyio
async def test_unexpired_lease_is_not_alerted(
    clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    await _wallet("w-hold")
    await _permit("p-hold", "w-hold")
    await _record("rec-hold", "w-hold", created_at=NOW - timedelta(seconds=15))
    holds_until = NOW - timedelta(seconds=GRACE - 10)
    await _attempt(
        "att-hold",
        "rec-hold",
        "w-hold",
        "p-hold",
        parked_at=NOW - timedelta(seconds=15),
        lease_owner="live-worker",
        lease_expires_at=holds_until,
        credits_charged="0",
    )

    with caplog.at_level("WARNING", logger="app.services.stuck_work_sweep"):
        result = await run_stuck_work_sweep(now=NOW)

    assert result.expired_lease_count == 0
    assert [r for r in caplog.records if r.message == "stuck_work_alert"] == []
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(McpDispatchAttemptModel, "att-hold")
        assert row is not None
        assert row.reconcile_lease_owner == "live-worker"
        assert row.reconcile_lease_expires_at == holds_until


@pytest.mark.anyio
async def test_aged_idempotency_needs_review_alerts_without_repair(
    clean_database, caplog: pytest.LogCaptureFixture
) -> None:
    await _wallet("w-review")
    await _ledger("led-review", "w-review")
    await _ledger("led-fresh-review", "w-review", amount="-1")
    await _record(
        "rec-review",
        "w-review",
        created_at=NOW - timedelta(seconds=AGE + 90),
        ledger_entry_id="led-review",
    )
    await _record(
        "rec-review-fresh",
        "w-review",
        created_at=NOW - timedelta(seconds=20),
        ledger_entry_id="led-fresh-review",
    )

    with caplog.at_level("WARNING", logger="app.services.stuck_work_sweep"):
        result = await run_stuck_work_sweep(now=NOW)

    assert result.idempotency_needs_review == 1
    assert result.idempotency_needs_review_oldest_age_seconds == AGE + 90
    alerts = [r for r in caplog.records if r.message == "stuck_work_alert"]
    assert len(alerts) == 1
    assert alerts[0].idempotency_needs_review == 1
    factory = get_session_factory()
    async with factory() as session:
        aged = await session.get(IdempotencyRecordModel, "rec-review")
        fresh = await session.get(IdempotencyRecordModel, "rec-review-fresh")
        assert aged is not None and fresh is not None
        assert aged.response_json is None
        assert fresh.response_json is None
        assert aged.ledger_entry_id == "led-review"


@pytest.mark.anyio
async def test_sweep_disabled_does_not_alert(
    clean_database, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "STUCK_WORK_SWEEP_ENABLED", False)
    await _wallet("w-off")
    await _permit("p-off", "w-off", spent="2")
    await _ledger("led-off", "w-off")
    await _record(
        "rec-off",
        "w-off",
        created_at=NOW - timedelta(hours=5),
        ledger_entry_id="led-off",
    )
    await _attempt(
        "att-off",
        "rec-off",
        "w-off",
        "p-off",
        parked_at=NOW - timedelta(hours=5),
        ledger_entry_id="led-off",
        lease_owner="crashed",
        lease_expires_at=NOW - timedelta(hours=2),
    )
    before = await _snapshot("att-off", "p-off", "w-off")

    with caplog.at_level("WARNING", logger="app.services.stuck_work_sweep"):
        result = await run_stuck_work_sweep(now=NOW)

    assert result.delivery_uncertain_aged == 0
    assert result.expired_lease_count == 0
    assert [r for r in caplog.records if r.message == "stuck_work_alert"] == []
    assert await _snapshot("att-off", "p-off", "w-off") == before
