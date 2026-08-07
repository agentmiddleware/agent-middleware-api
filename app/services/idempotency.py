from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    McpDispatchAttemptModel,
    ReceiptModel,
)
from app.services.signing_keys import sha256_hex

GOVERNED_MCP_IDEMPOTENCY_ENDPOINT = "/mcp/invoke"


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key is reused for a different request."""


class IdempotencyInProgressError(RuntimeError):
    """Raised when an idempotency key is already executing without a result."""


@dataclass(frozen=True)
class IdempotencyReplay:
    response_reference: str | None
    response_json: dict[str, Any] | None
    status_code: int


@dataclass(frozen=True)
class IdempotencyBegin:
    """Identity and replay result for one idempotent request."""

    record_id: str
    request_hash: str
    replay: IdempotencyReplay | None


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
    async def _wait_for_replay(
        self,
        session: AsyncSession,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> IdempotencyReplay:
        """Wait boundedly for an identical concurrent request to finalize."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            await session.rollback()
            await asyncio.sleep(poll_interval_seconds)
            session.expire_all()
            existing = (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        *_idempotency_predicates(
                            wallet_id,
                            endpoint,
                            idempotency_key,
                        )
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise IdempotencyInProgressError("idempotency_in_progress")
            try:
                replay = _replay_from_record(existing, request_hash)
            except IdempotencyInProgressError:
                continue
            assert replay is not None
            return replay
        raise IdempotencyInProgressError("idempotency_in_progress")

    async def begin_with_record(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        request_payload: dict[str, Any],
        operation_kind: str | None = None,
        wait_timeout_seconds: float = 0.0,
        poll_interval_seconds: float = 0.05,
    ) -> IdempotencyBegin:
        if wait_timeout_seconds < 0 or poll_interval_seconds <= 0:
            raise ValueError("idempotency_wait_invalid")
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
                try:
                    replay = _replay_from_record(existing, request_hash)
                except IdempotencyInProgressError:
                    if wait_timeout_seconds <= 0:
                        raise
                    replay = await self._wait_for_replay(
                        session,
                        wallet_id=wallet_id,
                        endpoint=endpoint,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        timeout_seconds=wait_timeout_seconds,
                        poll_interval_seconds=poll_interval_seconds,
                    )
                return IdempotencyBegin(
                    record_id=existing.record_id,
                    request_hash=request_hash,
                    replay=replay,
                )

            record = IdempotencyRecordModel(
                record_id=f"idm-{uuid.uuid4().hex[:16]}",
                wallet_id=wallet_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                operation_kind=operation_kind,
            )
            session.add(record)
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
                try:
                    replay = _replay_from_record(existing, request_hash)
                except IdempotencyInProgressError:
                    if wait_timeout_seconds <= 0:
                        raise
                    replay = await self._wait_for_replay(
                        session,
                        wallet_id=wallet_id,
                        endpoint=endpoint,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        timeout_seconds=wait_timeout_seconds,
                        poll_interval_seconds=poll_interval_seconds,
                    )
                return IdempotencyBegin(
                    record_id=existing.record_id,
                    request_hash=request_hash,
                    replay=replay,
                )
            except OperationalError as exc:
                # SQLite can report a write-contention race as "database is
                # locked" instead of a unique-key IntegrityError. Preserve the
                # same bounded replay behavior and never expose a raw 500.
                if "database is locked" not in str(exc):
                    raise
                await session.rollback()
                result = await session.execute(
                    select(IdempotencyRecordModel).where(
                        *_idempotency_predicates(
                            wallet_id,
                            endpoint,
                            idempotency_key,
                        )
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise IdempotencyInProgressError("idempotency_in_progress")
                try:
                    replay = _replay_from_record(existing, request_hash)
                except IdempotencyInProgressError:
                    if wait_timeout_seconds <= 0:
                        raise
                    replay = await self._wait_for_replay(
                        session,
                        wallet_id=wallet_id,
                        endpoint=endpoint,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        timeout_seconds=wait_timeout_seconds,
                        poll_interval_seconds=poll_interval_seconds,
                    )
                return IdempotencyBegin(
                    record_id=existing.record_id,
                    request_hash=request_hash,
                    replay=replay,
                )
            return IdempotencyBegin(
                record_id=record.record_id,
                request_hash=request_hash,
                replay=None,
            )

    async def begin(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        request_payload: dict[str, Any],
    ) -> IdempotencyReplay | None:
        """Compatibility wrapper returning only the optional replay."""
        begun = await self.begin_with_record(
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
        return begun.replay

    async def get_record(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
    ) -> IdempotencyRecordModel | None:
        factory = get_session_factory()
        async with factory() as session:
            return (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        *_idempotency_predicates(
                            wallet_id,
                            endpoint,
                            idempotency_key,
                        )
                    )
                )
            ).scalar_one_or_none()

    async def get_governed_mcp_record(
        self,
        *,
        wallet_id: str,
        idempotency_key: str,
    ) -> IdempotencyRecordModel | None:
        """Return the one row protected by the normalized MCP identity index."""
        factory = get_session_factory()
        async with factory() as session:
            return (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        col(IdempotencyRecordModel.wallet_id) == wallet_id,
                        col(IdempotencyRecordModel.idempotency_key) == idempotency_key,
                        or_(
                            col(IdempotencyRecordModel.endpoint)
                            == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                            col(IdempotencyRecordModel.endpoint) == "/mcp/messages",
                            col(IdempotencyRecordModel.endpoint).like(
                                "/mcp/tools/%/invoke"
                            ),
                        ),
                    )
                )
            ).scalar_one_or_none()

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
            record.response_json = (
                json.dumps(response_json, default=str) if response_json else None
            )
            record.status_code = status_code
            session.add(record)
            await session.commit()

    async def abandon(
        self,
        *,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
    ) -> None:
        """Release an in-progress record so the caller may retry the key.

        Used when a governed invoke stops on a retryable, side-effect-free
        condition (human approval still pending, approval backend
        unreachable): completing the record would replay that transient state
        forever, and leaving it in progress would reject the retry with
        ``idempotency_in_progress``. Only an uncharged, unfinished record is
        deleted — a completed response or a ``ledger_entry_id`` checkpoint
        means money moved, and the record must survive for replay/repair.
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
            if record.response_json is not None or record.ledger_entry_id:
                return
            await session.delete(record)
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
        """Repair governed idempotency records orphaned around finalization.

        Effect-free canonical MCP rows that never reached the atomic prepared
        checkpoint are deleted so the same key can safely retry. A governed
        invoke that did debit calls mark_charged() before finalization. For
        each such record idle for at least ``idle_seconds`` (so live in-flight
        requests are never touched):
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
                # The upstream pipeline creates its idempotency row before the
                # atomic permit-reservation/prepared-attempt transaction. A
                # crash in that narrow, effect-free gap leaves no budget,
                # debit, attempt, or receipt to recover. Expire only this
                # upstream MCP identity so a retry can safely start again.
                # Local tools share the canonical replay scope but have
                # different side-effect ordering and are excluded by the
                # internal operation kind.
                unstarted = (
                    (
                        await session.execute(
                            select(IdempotencyRecordModel)
                            .where(
                                cast(
                                    ColumnElement[bool],
                                    IdempotencyRecordModel.endpoint
                                    == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    IdempotencyRecordModel.operation_kind
                                    == "upstream_mcp",
                                ),
                                cast(
                                    ColumnElement[bool],
                                    cast(Any, IdempotencyRecordModel.response_json).is_(
                                        None
                                    ),
                                ),
                                cast(
                                    ColumnElement[bool],
                                    cast(
                                        Any, IdempotencyRecordModel.ledger_entry_id
                                    ).is_(None),
                                ),
                                cast(
                                    ColumnElement[bool],
                                    IdempotencyRecordModel.created_at < cutoff,
                                ),
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                for record in unstarted:
                    attempt_id = await session.scalar(
                        select(cast(Any, McpDispatchAttemptModel.attempt_id)).where(
                            cast(
                                ColumnElement[bool],
                                McpDispatchAttemptModel.idempotency_record_id
                                == record.record_id,
                            )
                        )
                    )
                    receipt_id = await session.scalar(
                        select(cast(Any, ReceiptModel.receipt_id)).where(
                            cast(
                                ColumnElement[bool],
                                ReceiptModel.idempotency_record_id == record.record_id,
                            )
                        )
                    )
                    if attempt_id is None and receipt_id is None:
                        await session.delete(record)
                        repaired += 1

                stuck = (
                    (
                        await session.execute(
                            select(IdempotencyRecordModel)
                            .where(
                                cast(
                                    ColumnElement[bool],
                                    cast(Any, IdempotencyRecordModel.response_json).is_(
                                        None
                                    ),
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
                    )
                    .scalars()
                    .all()
                )
                for record in stuck:
                    # Remote MCP attempts retain a bounded canonical upstream
                    # result and have a state-aware reconciler that can rebuild
                    # the exact replay contract. A generic receipt-only repair
                    # would discard that result and erase delivery uncertainty.
                    dispatch_attempt_id = await session.scalar(
                        select(cast(Any, McpDispatchAttemptModel.attempt_id)).where(
                            cast(
                                ColumnElement[bool],
                                McpDispatchAttemptModel.idempotency_record_id
                                == record.record_id,
                            )
                        )
                    )
                    if dispatch_attempt_id is not None:
                        continue
                    receipt = (
                        await session.execute(
                            select(ReceiptModel).where(
                                cast(
                                    ColumnElement[bool],
                                    ReceiptModel.idempotency_record_id
                                    == record.record_id,
                                )
                            )
                        )
                    ).scalar_one_or_none()
                    if receipt is None:
                        # Legacy receipts predate the explicit idempotency FK.
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
                        "delivery_uncertain": 504,
                        "response_rejected": 502,
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
