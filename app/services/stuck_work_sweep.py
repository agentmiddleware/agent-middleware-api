"""Alert on stuck governed work from ``periodic_cleanup``.

Independent of ``UPSTREAM_RECONCILE_WORKER_ENABLED``. Three checks:

1. Unresolved ``delivery_uncertain`` rows parked at least
   ``STUCK_WORK_UNCERTAIN_ALERT_AGE_SECONDS`` ago. One warning,
   ``stuck_work_alert``, with cumulative age buckets and the oldest age.
2. Reconcile leases whose ``reconcile_lease_expires_at`` is older than
   ``now - STUCK_WORK_LEASE_GRACE_SECONDS``. Count only. Claim already
   treats an expired lease as free (``DeliveryUncertainReconcileWorker
   ._due_conditions``: ``expires_at IS NULL OR expires_at <= now``, and the
   guarded UPDATE re-checks that predicate), so nulling owner/expires would
   not release a row a live holder still owns and would not unblock a row
   the next sweep can already claim. ``STUCK_WORK_LEASE_REAPER_ENABLED``
   gates this alert.
3. Idempotency records that ``reconcile_stuck_records`` would count as
   needing review, older than the same age threshold. This sweep does not
   repair them.

Nothing here changes attempt state, ledger rows, wallet balance, or permit
budget. Age is never a reason to release a reservation or redispatch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, func, or_, select
from sqlalchemy.sql import ColumnElement

from app.core.config import get_settings
from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    McpDispatchAttemptModel,
    ReceiptModel,
)

logger = logging.getLogger(__name__)

STUCK_WORK_ALERT_EVENT = "stuck_work_alert"
_DELIVERY_UNCERTAIN = "delivery_uncertain"
_BUCKET_MULTIPLIERS = (1, 6, 24)


@dataclass(frozen=True)
class StuckWorkSweepResult:
    """Counts from one sweep. ``leases_cleared`` is always 0."""

    delivery_uncertain_aged: int
    delivery_uncertain_oldest_age_seconds: int
    delivery_uncertain_buckets: dict[str, int]
    expired_lease_count: int
    idempotency_needs_review: int
    idempotency_needs_review_oldest_age_seconds: int
    leases_cleared: int = 0


def _empty_result() -> StuckWorkSweepResult:
    return StuckWorkSweepResult(
        delivery_uncertain_aged=0,
        delivery_uncertain_oldest_age_seconds=0,
        delivery_uncertain_buckets={"ge_1x": 0, "ge_6x": 0, "ge_24x": 0},
        expired_lease_count=0,
        idempotency_needs_review=0,
        idempotency_needs_review_oldest_age_seconds=0,
    )


def _is_null(column: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], cast(Any, column).is_(None))


def _is_not_null(column: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], cast(Any, column).is_not(None))


def _age_seconds(now: datetime, oldest: datetime | None) -> int:
    if oldest is None:
        return 0
    return int((now - to_naive_utc(oldest)).total_seconds())


async def run_stuck_work_sweep(*, now: datetime | None = None) -> StuckWorkSweepResult:
    """Read stuck work and emit ``stuck_work_alert`` when any count is non-zero.

    ``now`` is injectable for tests. Production passes nothing and uses
    ``utc_now``. Returns without a query when the master switch is off.
    """
    settings = get_settings()
    if not settings.STUCK_WORK_SWEEP_ENABLED:
        return _empty_result()

    moment = to_naive_utc(now if now is not None else utc_now())
    age_seconds = settings.STUCK_WORK_UNCERTAIN_ALERT_AGE_SECONDS
    cutoff = moment - timedelta(seconds=age_seconds)

    uncertain_aged, uncertain_oldest, buckets = await _delivery_uncertain_ages(
        moment, cutoff, age_seconds
    )
    expired_leases = 0
    if settings.STUCK_WORK_LEASE_REAPER_ENABLED:
        grace_cutoff = moment - timedelta(
            seconds=settings.STUCK_WORK_LEASE_GRACE_SECONDS
        )
        expired_leases = await _expired_lease_count(grace_cutoff)
    review_count, review_oldest = await _idempotency_needs_review(moment, cutoff)

    result = StuckWorkSweepResult(
        delivery_uncertain_aged=uncertain_aged,
        delivery_uncertain_oldest_age_seconds=uncertain_oldest,
        delivery_uncertain_buckets=buckets,
        expired_lease_count=expired_leases,
        idempotency_needs_review=review_count,
        idempotency_needs_review_oldest_age_seconds=review_oldest,
    )
    if uncertain_aged or expired_leases or review_count:
        logger.warning(
            STUCK_WORK_ALERT_EVENT,
            extra={
                "delivery_uncertain_aged": uncertain_aged,
                "delivery_uncertain_oldest_age_seconds": uncertain_oldest,
                "delivery_uncertain_buckets": buckets,
                "expired_lease_count": expired_leases,
                "idempotency_needs_review": review_count,
                "idempotency_needs_review_oldest_age_seconds": review_oldest,
                "alert_age_seconds": age_seconds,
                "leases_cleared": 0,
                "lease_reaper": "alert_only",
            },
        )
    return result


async def _delivery_uncertain_ages(
    now: datetime, cutoff: datetime, age_seconds: int
) -> tuple[int, int, dict[str, int]]:
    """Unresolved parked calls at least ``age_seconds`` old.

    Resolved rows stay ``delivery_uncertain`` (state is never rewritten) and
    are excluded: they already have a recorded reconcile outcome. Parked time
    matches the reconcile worker: ``coalesce(completed_at, updated_at)``.
    Buckets are cumulative multiples of the configured age (1x, 6x, 24x).
    """
    attempt = McpDispatchAttemptModel
    parked_at = func.coalesce(attempt.completed_at, attempt.updated_at)
    bucket_sums = [
        func.coalesce(
            func.sum(
                case(
                    (
                        parked_at <= now - timedelta(seconds=age_seconds * multiplier),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        for multiplier in _BUCKET_MULTIPLIERS
    ]
    stmt = select(func.count(), func.min(parked_at), *bucket_sums).where(
        cast(ColumnElement[bool], attempt.state == _DELIVERY_UNCERTAIN),
        _is_null(attempt.reconcile_status),
        cast(ColumnElement[bool], parked_at <= cutoff),
    )
    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(stmt)).one()
    buckets = {
        f"ge_{multiplier}x": int(row[index + 2] or 0)
        for index, multiplier in enumerate(_BUCKET_MULTIPLIERS)
    }
    return int(row[0] or 0), _age_seconds(now, row[1]), buckets


async def _expired_lease_count(grace_cutoff: datetime) -> int:
    """Leases past the grace window. Does not UPDATE.

    A live holder has ``reconcile_lease_expires_at`` in the future, so it is
    outside this predicate. An expired lease is already free for
    ``claim_due_calls``; this count is the operator signal that a crashed
    sweep left owner/expires set.
    """
    attempt = McpDispatchAttemptModel
    stmt = select(func.count()).where(
        _is_not_null(attempt.reconcile_lease_owner),
        cast(
            ColumnElement[bool],
            cast(Any, attempt.reconcile_lease_expires_at) < grace_cutoff,
        ),
    )
    factory = get_session_factory()
    async with factory() as session:
        count = (await session.execute(stmt)).scalar_one()
    return int(count or 0)


async def _idempotency_needs_review(now: datetime, cutoff: datetime) -> tuple[int, int]:
    """Same predicate ``reconcile_stuck_records`` increments, read-only.

    Charged (or ``awi_http``) rows with no response, no dispatch attempt, and
    no receipt, created at or before ``cutoff``. Rows the repair pass would
    complete or delete are not counted.
    """
    record = IdempotencyRecordModel
    attempt = McpDispatchAttemptModel
    receipt = ReceiptModel
    attempt_for_record = (
        select(cast(Any, attempt.attempt_id))
        .where(
            cast(
                ColumnElement[bool],
                attempt.idempotency_record_id == record.record_id,
            )
        )
        .exists()
    )
    receipt_for_record = (
        select(cast(Any, receipt.receipt_id))
        .where(
            cast(
                ColumnElement[bool],
                receipt.idempotency_record_id == record.record_id,
            )
        )
        .exists()
    )
    receipt_for_ledger = (
        select(cast(Any, receipt.receipt_id))
        .where(
            _is_not_null(record.ledger_entry_id),
            cast(
                ColumnElement[bool],
                receipt.ledger_entry_id == record.ledger_entry_id,
            ),
        )
        .exists()
    )
    charged_or_awi = or_(
        _is_not_null(record.ledger_entry_id),
        cast(ColumnElement[bool], record.operation_kind == "awi_http"),
    )
    no_ledger_receipt = or_(_is_null(record.ledger_entry_id), ~receipt_for_ledger)
    stmt = select(func.count(), func.min(record.created_at)).where(
        _is_null(record.response_json),
        cast(ColumnElement[bool], record.created_at <= cutoff),
        charged_or_awi,
        ~attempt_for_record,
        ~receipt_for_record,
        no_ledger_receipt,
    )
    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(stmt)).one()
    return int(row[0] or 0), _age_seconds(now, row[1])
