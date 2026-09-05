from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col

from app.core.config import get_settings
from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    ReceiptModel,
)
from app.services.signing_keys import sha256_hex

GOVERNED_MCP_IDEMPOTENCY_ENDPOINT = "/mcp/invoke"


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key is reused for a different request."""


class IdempotencyInProgressError(RuntimeError):
    """Raised when an idempotency key is already executing without a result."""


# The store persists a client key verbatim: ``IdempotencyRecordModel.
# idempotency_key`` is ``VARCHAR(128)`` (migration 016). A key the store cannot
# hold is refused at the boundary — never truncated (two distinct client keys
# would collapse into one replay identity) and never swapped for a generated
# key (the client's retry would become a second charged action).
MAX_IDEMPOTENCY_KEY_LENGTH = 128


class InvalidIdempotencyKeyError(ValueError):
    """The caller supplied an idempotency key that is present but unusable.

    Distinct from "no key supplied": an absent key falls through to the
    surface's documented default (a generated per-call key, or
    ``idempotency_key_required`` where a key is mandatory). A key the client
    did send but that cannot serve as a replay identity must be rejected
    before any permit is minted, tool executed, or wallet charged — silently
    defaulting it would turn the client's retry into a second action.

    ``reason_code`` names the defect (``idempotency_key_empty``,
    ``idempotency_key_not_a_string``, ``idempotency_key_too_long``,
    ``idempotency_key_conflict``); ``sources`` names where on the request the
    offending value(s) were carried.
    """

    def __init__(self, reason_code: str, *, sources: tuple[str, ...]) -> None:
        super().__init__("invalid_idempotency_key")
        self.reason_code = reason_code
        self.sources = sources


def validate_idempotency_key(value: object, *, source: str) -> str:
    """Return ``value`` as a usable client idempotency key or raise.

    Only call this with a value the client actually supplied; deciding what
    "absent" means belongs to the caller (see
    :func:`resolve_client_idempotency_key`).
    """
    if not isinstance(value, str):
        raise InvalidIdempotencyKeyError(
            "idempotency_key_not_a_string", sources=(source,)
        )
    if not value.strip():
        raise InvalidIdempotencyKeyError("idempotency_key_empty", sources=(source,))
    if len(value) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidIdempotencyKeyError(
            "idempotency_key_too_long", sources=(source,)
        )
    return value


def resolve_client_idempotency_key(
    candidates: Iterable[tuple[str, object]],
) -> str | None:
    """Resolve the caller's replay key from every transport that carried one.

    ``candidates`` holds ``(source, value)`` pairs for each place the client
    actually put a key: the ``Idempotency-Key`` header (one pair per header
    line), ``params._meta`` on the standard endpoint, ``mcpContext`` on the
    legacy JSON-RPC route. Transports that carried nothing are simply not
    listed, and an explicit JSON ``null`` counts as nothing — it is how
    optional fields serialize, and ``McpContext.idempotency_key`` is declared
    ``str | None``.

    Every supplied value must validate, and all supplied values must agree.
    Two different keys on one request is an ambiguity about which operation
    identity the client meant; the store must never pick one.
    """
    resolved: list[tuple[str, str]] = []
    for source, value in candidates:
        if value is None:
            continue
        resolved.append((source, validate_idempotency_key(value, source=source)))
    if not resolved:
        return None
    distinct = {key for _, key in resolved}
    if len(distinct) > 1:
        raise InvalidIdempotencyKeyError(
            "idempotency_key_conflict",
            sources=tuple(dict.fromkeys(source for source, _ in resolved)),
        )
    return distinct.pop()


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
    async def _try_reconcile_and_replay(
        self,
        session: AsyncSession,
        *,
        existing: IdempotencyRecordModel,
        request_hash: str,
        wallet_id: str,
        endpoint: str,
        idempotency_key: str,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> IdempotencyReplay:
        """Try immediate reconciliation for dispatched/terminal attempts before wait."""
        # Check if there's a dispatch attempt linked to this idempotency record
        # that is either dispatched (ambiguous) or terminal but not finalized.
        dispatch_attempt = (
            await session.execute(
                select(McpDispatchAttemptModel).where(
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.idempotency_record_id
                        == existing.record_id,
                    )
                )
            )
        ).scalar_one_or_none()

        if dispatch_attempt is not None:
            # Import here to avoid circular dependency
            from app.services.mcp_dispatch_attempts import (
                DISPATCH_TERMINAL_STATES,
                dispatch_reconciliation_idle_seconds,
            )
            from app.services.mcp_dispatch_reconciliation import (
                get_mcp_dispatch_reconciliation_service,
            )

            # Terminal rows own no send authority. Repair their missing receipt
            # or replay immediately; the long idle window exists only to avoid
            # stealing a live prepared/claimed attempt.
            if dispatch_attempt.state in DISPATCH_TERMINAL_STATES:
                if existing.response_json is not None:
                    replay = _replay_from_record(existing, request_hash)
                    if replay is not None:
                        return replay
                should_reconcile = True
                reconcile_idle_seconds: int | None = None
            else:
                should_reconcile = False
                reconcile_idle_seconds = None

            # Only reconcile active attempts that are truly stale, using the
            # same globally conservative idle window as the periodic sweep.
            # Live attempts with active owners must wait, not be stolen.
            # Check staleness using updated_at (last state change), matching
            # list_stale_contexts logic in mcp_dispatch_attempts.py
            if (
                dispatch_attempt.state not in DISPATCH_TERMINAL_STATES
                and dispatch_attempt.updated_at is not None
            ):
                settings = get_settings()
                stale_idle_seconds = dispatch_reconciliation_idle_seconds(
                    connect_timeout_seconds=(
                        settings.MCP_UPSTREAM_CONNECT_TIMEOUT_SECONDS
                    ),
                    call_timeout_seconds=settings.MCP_UPSTREAM_CALL_TIMEOUT_SECONDS,
                )
                cutoff = to_naive_utc(utc_now() - timedelta(seconds=stale_idle_seconds))
                updated_naive = to_naive_utc(dispatch_attempt.updated_at)
                is_stale = updated_naive < cutoff

                if is_stale:
                    # Attempt exceeded the configured live-call window.
                    should_reconcile = True
                    reconcile_idle_seconds = stale_idle_seconds
                # else: fresh update, assume live owner, wait

            if should_reconcile:
                reconciler = get_mcp_dispatch_reconciliation_service()
                attempt_id = dispatch_attempt.attempt_id
                # The lookup transaction otherwise retains the application's
                # only pooled connection while reconciliation opens its own
                # session. Release it before crossing that service boundary.
                await session.rollback()
                session.expire_all()
                try:
                    await reconciler.reconcile_attempt(
                        attempt_id,
                        prepared_error_code="reconciled_stale_prepared",
                        idle_seconds=reconcile_idle_seconds,
                    )
                except Exception:
                    # Reconciliation failed; fall through to normal wait path
                    pass
                else:
                    # Reconciliation succeeded; re-read the record
                    fresh = (
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
                    if fresh is not None and fresh.response_json is not None:
                        replay = _replay_from_record(fresh, request_hash)
                        if replay is not None:
                            return replay

        # No dispatch attempt or reconciliation failed/incomplete; wait normally
        if wait_timeout_seconds <= 0:
            raise IdempotencyInProgressError("idempotency_in_progress")
        return await self._wait_for_replay(
            session,
            wallet_id=wallet_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

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
                    # Before declaring in-progress, check if there's a terminal or
                    # dispatched attempt that can be reconciled immediately.
                    replay = await self._try_reconcile_and_replay(
                        session,
                        existing=existing,
                        request_hash=request_hash,
                        wallet_id=wallet_id,
                        endpoint=endpoint,
                        idempotency_key=idempotency_key,
                        wait_timeout_seconds=wait_timeout_seconds,
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
                    replay = await self._try_reconcile_and_replay(
                        session,
                        existing=existing,
                        request_hash=request_hash,
                        wallet_id=wallet_id,
                        endpoint=endpoint,
                        idempotency_key=idempotency_key,
                        wait_timeout_seconds=wait_timeout_seconds,
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
                    replay = await self._try_reconcile_and_replay(
                        session,
                        existing=existing,
                        request_hash=request_hash,
                        wallet_id=wallet_id,
                        endpoint=endpoint,
                        idempotency_key=idempotency_key,
                        wait_timeout_seconds=wait_timeout_seconds,
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

                # Local governed calls fall through both passes above: the
                # unstarted pass is scoped to operation_kind="upstream_mcp",
                # and the stuck pass below requires a linked ledger_entry_id.
                # A crash between the committed debit and the write that
                # attaches that debit to the record therefore left an
                # unresolvable row -- response_json IS NULL and
                # ledger_entry_id IS NULL -- that no branch selected, so it
                # never repaired and never counted toward needs_review. The
                # charge carries operation_key=record_id (see the governed
                # money.charge call in app/routers/mcp.py), so the orphaned
                # debit is recoverable by that key: link it here and the stuck
                # pass below resolves it exactly like any other crashed
                # finalization. Engine-independent -- no row-lock behaviour
                # involved.
                orphaned_local = (
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
                                    IdempotencyRecordModel.operation_kind == "local",
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
                for record in orphaned_local:
                    debit = (
                        await session.execute(
                            select(LedgerEntryModel).where(
                                cast(
                                    ColumnElement[bool],
                                    LedgerEntryModel.wallet_id == record.wallet_id,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    LedgerEntryModel.operation_key == record.record_id,
                                ),
                                # Compensation proof means money left the
                                # wallet. The wallet/operation-key uniqueness
                                # constraint already makes a same-key credit
                                # impossible alongside the debit, but stating
                                # the direction here means this pass can never
                                # adopt a credit as evidence of a charge.
                                cast(
                                    ColumnElement[bool],
                                    LedgerEntryModel.amount < 0,
                                ),
                            )
                        )
                    ).scalar_one_or_none()
                    if debit is None:
                        # Nothing provably moved, and a local identity must NOT
                        # be expired on that basis: local tools run their side
                        # effect before the debit exists, so deleting the record
                        # would let a retry execute it a second time. That
                        # invariant is asserted by
                        # test_stale_local_identity_is_not_deleted_without
                        # _compensation_proof. Leave it exactly as found.
                        continue
                    # A committed debit is compensation proof: money moved under
                    # this identity. Link it, and the stuck pass below resolves
                    # it from the receipt or counts it for manual review.
                    record.ledger_entry_id = debit.entry_id
                    session.add(record)
                # The session does not autoflush, so the links just written are
                # still pending; flush them so the stuck pass below selects the
                # rows this pass just repaired into scope.
                await session.flush()

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
