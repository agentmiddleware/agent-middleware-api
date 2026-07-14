from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, ReceiptModel
from app.services.signing_keys import sha256_hex


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key is reused for a different request."""


class IdempotencyInProgressError(RuntimeError):
    """Raised when an idempotency key is already executing without a result."""


@dataclass(frozen=True)
class IdempotencyReplay:
    response_reference: str | None
    response_json: dict[str, Any] | None
    status_code: int


def _idempotency_predicates(
    wallet_id: str, endpoint: str, idempotency_key: str
) -> tuple[ColumnElement[bool], ...]:
    return (
        cast(ColumnElement[bool], IdempotencyRecordModel.wallet_id == wallet_id),
        cast(ColumnElement[bool], IdempotencyRecordModel.endpoint == endpoint),
        cast(
            ColumnElement[bool],
            IdempotencyRecordModel.idempotency_key == idempotency_key,
        ),
    )


def _replay_from_record(
    existing: IdempotencyRecordModel, request_hash: str
) -> IdempotencyReplay | None:
    if existing.request_hash != request_hash:
        raise IdempotencyConflictError("idempotency_key_reused")
    if existing.response_json:
        try:
            decoded = json.loads(existing.response_json)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return IdempotencyReplay(
                response_reference=existing.response_reference,
                response_json=decoded,
                status_code=existing.status_code,
            )
    raise IdempotencyInProgressError("idempotency_in_progress")


class IdempotencyService:
    async def begin(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        request_payload: dict[str, Any],
    ) -> IdempotencyReplay | None:
        request_hash = sha256_hex(request_payload)
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    *_idempotency_predicates(wallet_id, endpoint, idempotency_key)
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                return _replay_from_record(existing, request_hash)

            session.add(
                IdempotencyRecordModel(
                    record_id=f"idm-{uuid.uuid4().hex[:16]}",
                    wallet_id=wallet_id,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # Lost a race to a concurrent identical request: the other
                # request's row already landed under the unique constraint.
                # Treat it the same as finding it on the initial SELECT
                # instead of surfacing a raw 500 to the caller.
                await session.rollback()
                result = await session.execute(
                    select(IdempotencyRecordModel).where(
                        *_idempotency_predicates(wallet_id, endpoint, idempotency_key)
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise
                return _replay_from_record(existing, request_hash)
            return None

    async def complete(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        response_reference: str | None,
        response_json: dict[str, Any] | None,
        status_code: int = 200,
    ) -> None:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    *_idempotency_predicates(wallet_id, endpoint, idempotency_key)
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                return
            record.response_reference = response_reference
            record.response_json = json.dumps(response_json, default=str) if response_json else None
            record.status_code = status_code
            session.add(record)
            await session.commit()

    async def mark_charged(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        ledger_entry_id: str,
    ) -> None:
        """Checkpoint that this idempotency record's charge has landed.

        Called right after a governed invoke charges a wallet and before the
        receipt/audit/complete finalization sequence runs, so a later crash
        that leaves the record stuck "in progress" can be told apart from a
        record that was never charged at all -- see reconcile_stuck_records.
        """
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    *_idempotency_predicates(wallet_id, endpoint, idempotency_key)
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                return
            record.ledger_entry_id = ledger_entry_id
            session.add(record)
            await session.commit()

    async def reconcile_stuck_records(
        self, *, idle_seconds: int = 900
    ) -> tuple[int, int]:
        """Repair idempotency records orphaned by a crash between charge and
        finalization (receipt write, audit write, complete()).

        A governed invoke calls mark_charged() right after the wallet charge
        lands and before finalization, so the only way a record can be both
        idle and still "in progress" (response_json is null) is a process
        death somewhere in that window. For each such record idle for at
        least idle_seconds (so live in-flight requests are never touched):
        if a receipt already exists for its ledger_entry_id (finalization got
        as far as writing the receipt but not completing this record), the
        record is completed from that receipt so a retry replays cleanly
        instead of hanging forever on IdempotencyInProgressError. If no
        receipt exists at all, the charge succeeded but nothing about it can
        be safely reconstructed after the fact (the original tool response
        was never persisted) -- these are left untouched and counted
        separately for manual/operator review.

        Returns (repaired_count, needs_manual_review_count).
        """
        # created_at is a naive-UTC DateTime column (see app.core.time.utc_now);
        # build the idle cutoff naive too so the SQL comparison isn't skewed by
        # a tz-aware parameter being cast against the session timezone on
        # Postgres.
        cutoff = utc_now() - timedelta(seconds=idle_seconds)
        factory = get_session_factory()
        repaired = 0
        needs_review = 0
        async with factory() as session:
            async with session.begin():
                stuck = (
                    await session.execute(
                        select(IdempotencyRecordModel).where(
                            cast(
                                ColumnElement[bool],
                                cast(Any, IdempotencyRecordModel.response_json).is_(None),
                            ),
                            cast(
                                ColumnElement[bool],
                                cast(
                                    Any, IdempotencyRecordModel.ledger_entry_id
                                ).is_not(None),
                            ),
                            cast(
                                ColumnElement[bool],
                                IdempotencyRecordModel.created_at < cutoff,
                            ),
                        )
                        .with_for_update()
                    )
                ).scalars().all()
                for record in stuck:
                    receipt = (
                        await session.execute(
                            select(ReceiptModel).where(
                                cast(
                                    ColumnElement[bool],
                                    ReceiptModel.ledger_entry_id
                                    == record.ledger_entry_id,
                                )
                            )
                        )
                    ).scalar_one_or_none()
                    if receipt is None:
                        needs_review += 1
                        continue
                    # The receipt's outcome is the ground truth -- a crash can
                    # leave a failed_refunded/denied/insufficient_funds
                    # receipt just as easily as a success one (e.g. a crash
                    # inside _finalize_governed_denial between the receipt
                    # write and idem.complete()). Reconciling it as a bare 200
                    # success regardless of outcome would tell a replaying
                    # client the call succeeded when it didn't.
                    is_error = receipt.outcome != "success"
                    status_code = {
                        "success": 200,
                        "insufficient_funds": 402,
                        "denied": 403,
                    }.get(receipt.outcome, 500)
                    recovered_response = {
                        "reconciled": True,
                        "outcome": receipt.outcome,
                        "isError": is_error,
                        "receipt_id": receipt.receipt_id,
                        "ledger_entry_id": record.ledger_entry_id,
                        "message": (
                            "The original response could not be replayed: "
                            "finalization crashed after the charge and "
                            f"receipt (outcome={receipt.outcome!r}) were "
                            "already written. Inspect "
                            f"/v1/evidence/{receipt.receipt_id} for the "
                            "full record of what happened."
                        ),
                    }
                    if is_error:
                        recovered_response["error"] = receipt.outcome
                    record.response_reference = receipt.receipt_id
                    record.response_json = json.dumps(recovered_response)
                    record.status_code = status_code
                    session.add(record)
                    repaired += 1
        return repaired, needs_review


_service: IdempotencyService | None = None


def get_idempotency_service() -> IdempotencyService:
    global _service
    if _service is None:
        _service = IdempotencyService()
    return _service
