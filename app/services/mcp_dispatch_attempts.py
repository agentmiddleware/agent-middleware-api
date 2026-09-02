"""Durable state machine for governed upstream MCP dispatch attempts."""

from __future__ import annotations

import hashlib
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    HumanApprovalModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    ReceiptModel,
)
from app.services.permits import PermitService, PermitValidation, get_permit_service
from app.services.signing_keys import canonical_json, sha256_hex

DISPATCH_PREPARED = "prepared"
DISPATCH_LEGACY_DISPATCHED = "dispatched"
DISPATCH_CLAIMED = "dispatch_claimed"
DISPATCH_TERMINAL_STATES = frozenset(
    {
        "succeeded",
        "returned_error",
        "delivery_uncertain",
        "response_rejected",
    }
)
DISPATCH_SENT_STATES = frozenset({DISPATCH_LEGACY_DISPATCHED, DISPATCH_CLAIMED})
DISPATCH_ACTIVE_STATES = frozenset({DISPATCH_PREPARED, *DISPATCH_SENT_STATES})
_MIN_DISPATCH_IDLE_SECONDS = 300
_DISPATCH_CLEANUP_MARGIN_SECONDS = 30
# These maxima are a rolling-deployment safety contract. Reconciliation uses
# their derived lifetime even when one worker has smaller local settings, so a
# newly deployed worker cannot reap a still-live claim created by an older one.
MAX_UPSTREAM_CONNECT_TIMEOUT_SECONDS = 600
MAX_UPSTREAM_CALL_TIMEOUT_SECONDS = 3600
_DISPATCH_RECONCILIATION_IDLE_SECONDS = max(
    _MIN_DISPATCH_IDLE_SECONDS,
    MAX_UPSTREAM_CONNECT_TIMEOUT_SECONDS
    + (3 * MAX_UPSTREAM_CALL_TIMEOUT_SECONDS)
    + _DISPATCH_CLEANUP_MARGIN_SECONDS,
)


class DispatchAttemptError(RuntimeError):
    """Base error for invalid or conflicting dispatch persistence."""


class DispatchAttemptConflictError(DispatchAttemptError):
    """One durable dispatch identity was reused with different invariants."""


class DispatchPrepareRolledBackError(DispatchAttemptError):
    """Remote preparation failed and recovery proved that nothing committed."""


class DispatchPrepareCommitUncertainError(DispatchAttemptConflictError):
    """Remote preparation may have committed and must not be compensated here."""


class DispatchClaimUnavailableError(DispatchAttemptConflictError):
    """The one-shot authority to send this invocation is already owned."""


class DispatchResultRejectedError(DispatchAttemptError):
    """A confirmed upstream result cannot be represented in durable storage."""


class DispatchResultTooLargeError(DispatchResultRejectedError):
    """The serialized upstream result exceeds its configured storage bound."""


def dispatch_reconciliation_idle_seconds(
    *,
    connect_timeout_seconds: float,
    call_timeout_seconds: float,
) -> int:
    """Return the fixed maximum lifetime for any supported live call."""
    if (
        not math.isfinite(connect_timeout_seconds)
        or not math.isfinite(call_timeout_seconds)
        or connect_timeout_seconds <= 0
        or call_timeout_seconds <= 0
    ):
        raise ValueError("dispatch_timeout_invalid")
    if (
        connect_timeout_seconds > MAX_UPSTREAM_CONNECT_TIMEOUT_SECONDS
        or call_timeout_seconds > MAX_UPSTREAM_CALL_TIMEOUT_SECONDS
    ):
        raise ValueError("dispatch_timeout_exceeds_supported_maximum")
    return _DISPATCH_RECONCILIATION_IDLE_SECONDS


@dataclass(frozen=True)
class DispatchAttemptContext:
    """Attempt plus the request identity needed for idempotent completion."""

    attempt: McpDispatchAttemptModel
    endpoint: str
    idempotency_key: str


@dataclass(frozen=True)
class DispatchAttemptMetrics:
    """Payload-free operator metrics for the remote dispatch state machine."""

    state_counts: dict[str, int]
    stale_active: int
    unfinalized_terminal: int
    terminal_idempotency_incomplete: int

    @property
    def reconciliation_backlog(self) -> int:
        return (
            self.stale_active
            + self.unfinalized_terminal
            + self.terminal_idempotency_incomplete
        )


async def _claim_debit_is_valid(
    session: AsyncSession,
    attempt: McpDispatchAttemptModel,
) -> bool:
    """Verify the debit linked to an attempt before granting send authority."""
    if attempt.ledger_entry_id is None or attempt.credits_charged <= 0:
        return False
    ledger = await session.get(LedgerEntryModel, attempt.ledger_entry_id)
    return bool(
        ledger is not None
        and ledger.wallet_id == attempt.wallet_id
        and ledger.action == "debit"
        and ledger.operation_key == attempt.idempotency_record_id
        and ledger.amount == -attempt.credits_charged
    )


def _unsupported_upstream_constraints(permit: PermitModel) -> list[str]:
    """Return constraints the atomic upstream reservation cannot yet enforce.

    The prepare path can atomically reserve a flat per-call cost, but the
    per-tool call cap and the aggregate value cap are not yet enforceable
    inside that single guarded reservation. When either is configured, a
    prepared row must be treated as commit-uncertain rather than adopted as a
    clean success or turned into a denial receipt.
    """
    return [
        name
        for name, configured in (
            ("max_calls_per_tool", permit.max_calls_per_tool_json is not None),
            ("aggregate_value_cap", permit.aggregate_value_cap is not None),
        )
        if configured
    ]


def _assert_sha256(value: str) -> str:
    if len(value) != 64:
        raise DispatchAttemptError("dispatch_request_hash_invalid")
    try:
        int(value, 16)
    except ValueError as exc:
        raise DispatchAttemptError("dispatch_request_hash_invalid") from exc
    return value.lower()


def _assert_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise DispatchAttemptError("dispatch_upstream_origin_invalid")
    return value


def _bounded_result(
    payload: dict[str, Any] | None,
    *,
    max_result_bytes: int,
) -> tuple[str | None, int | None, str | None]:
    if max_result_bytes <= 0:
        raise DispatchAttemptError("dispatch_result_limit_invalid")
    if payload is None:
        return None, None, None
    try:
        serialized = canonical_json(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DispatchResultRejectedError("dispatch_result_invalid") from exc
    size = len(serialized.encode("utf-8"))
    if size > max_result_bytes:
        raise DispatchResultTooLargeError("dispatch_result_too_large")
    return serialized, size, sha256_hex(serialized)


def _validated_terminal_result(
    *,
    state: str,
    result_payload: dict[str, Any] | None,
    error_code: str | None,
    max_result_bytes: int,
) -> tuple[str | None, int | None, str | None]:
    if state not in DISPATCH_TERMINAL_STATES:
        raise DispatchAttemptError("dispatch_terminal_state_invalid")
    if state == "succeeded" and result_payload is None:
        raise DispatchAttemptError("dispatch_success_result_required")
    if error_code is not None and (
        not error_code or len(error_code) > 64 or error_code != error_code.strip()
    ):
        raise DispatchAttemptError("dispatch_error_code_invalid")
    return _bounded_result(
        result_payload,
        max_result_bytes=max_result_bytes,
    )


class McpDispatchAttemptService:
    """Persist one monotonic upstream dispatch state per idempotency record."""

    @staticmethod
    async def _get_by_idempotency_record(
        session: AsyncSession,
        idempotency_record_id: str,
    ) -> McpDispatchAttemptModel | None:
        return (
            await session.execute(
                select(McpDispatchAttemptModel).where(
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.idempotency_record_id
                        == idempotency_record_id,
                    )
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _assert_approval_binding(
        session: AsyncSession,
        *,
        record: IdempotencyRecordModel,
        permit: PermitModel,
        approval_id: str | None,
        wallet_id: str,
        public_tool_id: str,
    ) -> None:
        """Bind an approval-required dispatch to its consumed decision.

        The human decision is consumed before permit budget moves. Persisting
        that exact identity on ``prepared`` makes the authorization evidence
        recoverable even if the request worker crashes before it signs a
        receipt.
        """
        if not permit.requires_human_approval:
            if approval_id is not None:
                raise DispatchAttemptConflictError("dispatch_approval_linkage_invalid")
            return
        if approval_id is None:
            raise DispatchAttemptConflictError("dispatch_approval_required")
        approval = await session.get(HumanApprovalModel, approval_id)
        if (
            approval is None
            or approval.wallet_id != wallet_id
            or approval.permit_id != permit.permit_id
            or approval.tool != public_tool_id
            or approval.idempotency_key != record.idempotency_key
            or approval.status != "consumed"
        ):
            raise DispatchAttemptConflictError("dispatch_approval_linkage_invalid")

    @staticmethod
    def _assert_prepared_match(
        attempt: McpDispatchAttemptModel,
        *,
        idempotency_record_id: str,
        wallet_id: str,
        permit_id: str,
        approval_id: str | None,
        key_id: str | None,
        public_tool_id: str,
        upstream_tool_name: str,
        upstream_origin: str,
        request_hash: str,
        credits_authorized: Decimal,
    ) -> None:
        expected = {
            "idempotency_record_id": idempotency_record_id,
            "wallet_id": wallet_id,
            "permit_id": permit_id,
            "approval_id": approval_id,
            "key_id": key_id,
            "public_tool_id": public_tool_id,
            "upstream_tool_name": upstream_tool_name,
            "upstream_origin": upstream_origin,
            "request_hash": request_hash,
            "credits_authorized": credits_authorized,
        }
        if any(getattr(attempt, name) != value for name, value in expected.items()):
            raise DispatchAttemptConflictError("dispatch_idempotency_conflict")

    async def prepare(
        self,
        *,
        idempotency_record_id: str,
        wallet_id: str,
        permit_id: str,
        approval_id: str | None = None,
        key_id: str | None,
        public_tool_id: str,
        upstream_tool_name: str,
        upstream_origin: str,
        request_hash: str,
        credits_authorized: Decimal,
    ) -> McpDispatchAttemptModel:
        request_hash = _assert_sha256(request_hash)
        upstream_origin = _assert_origin(upstream_origin)
        if (
            not idempotency_record_id
            or not wallet_id
            or not permit_id
            or not public_tool_id
            or not upstream_tool_name
            or credits_authorized < 0
        ):
            raise DispatchAttemptError("dispatch_prepare_invalid")

        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                record = (
                    await session.execute(
                        select(IdempotencyRecordModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                IdempotencyRecordModel.record_id
                                == idempotency_record_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                IdempotencyRecordModel.wallet_id == wallet_id,
                            ),
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if record is None or record.request_hash != request_hash:
                    raise DispatchAttemptConflictError(
                        "dispatch_idempotency_record_invalid"
                    )
                permit = await session.get(PermitModel, permit_id)
                if permit is None:
                    raise DispatchAttemptConflictError("dispatch_permit_not_found")
                await self._assert_approval_binding(
                    session,
                    record=record,
                    permit=permit,
                    approval_id=approval_id,
                    wallet_id=wallet_id,
                    public_tool_id=public_tool_id,
                )

                existing = await self._get_by_idempotency_record(
                    session,
                    idempotency_record_id,
                )
                if existing is not None:
                    self._assert_prepared_match(
                        existing,
                        idempotency_record_id=idempotency_record_id,
                        wallet_id=wallet_id,
                        permit_id=permit_id,
                        approval_id=approval_id,
                        key_id=key_id,
                        public_tool_id=public_tool_id,
                        upstream_tool_name=upstream_tool_name,
                        upstream_origin=upstream_origin,
                        request_hash=request_hash,
                        credits_authorized=credits_authorized,
                    )
                    return existing

                attempt = McpDispatchAttemptModel(
                    attempt_id=f"dsp-{uuid.uuid4().hex[:16]}",
                    idempotency_record_id=idempotency_record_id,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    approval_id=approval_id,
                    key_id=key_id,
                    public_tool_id=public_tool_id,
                    upstream_tool_name=upstream_tool_name,
                    upstream_origin=upstream_origin,
                    request_hash=request_hash,
                    credits_authorized=credits_authorized,
                    state=DISPATCH_PREPARED,
                )
                session.add(attempt)
                try:
                    await session.flush()
                except IntegrityError:
                    # The locked idempotency row normally serializes this path;
                    # retain a uniqueness-race recovery for non-service writers.
                    await session.rollback()
                    async with factory() as recovery_session:
                        existing = await self._get_by_idempotency_record(
                            recovery_session,
                            idempotency_record_id,
                        )
                    if existing is None:
                        raise
                    self._assert_prepared_match(
                        existing,
                        idempotency_record_id=idempotency_record_id,
                        wallet_id=wallet_id,
                        permit_id=permit_id,
                        approval_id=approval_id,
                        key_id=key_id,
                        public_tool_id=public_tool_id,
                        upstream_tool_name=upstream_tool_name,
                        upstream_origin=upstream_origin,
                        request_hash=request_hash,
                        credits_authorized=credits_authorized,
                    )
                    return existing
                return attempt

    async def authorize_reserve_and_prepare(
        self,
        *,
        idempotency_record_id: str,
        wallet_id: str,
        permit_id: str,
        approval_id: str | None = None,
        key_id: str | None,
        public_tool_id: str,
        upstream_tool_name: str,
        upstream_origin: str,
        request_hash: str,
        credits_authorized: Decimal,
        arguments: dict[str, Any] | None = None,
        permit_service: PermitService | None = None,
    ) -> tuple[PermitValidation, McpDispatchAttemptModel | None]:
        """Atomically reserve permit budget and establish ``prepared``.

        The idempotency record, permit row, reservation, and attempt identity
        are locked in one transaction. Therefore every durable reservation has
        a row the reconciler can compensate, and a failed transaction leaves
        neither. A post-commit acknowledgement loss is recovered by adopting
        only an invariant-equivalent prepared row.
        """
        request_hash = _assert_sha256(request_hash)
        upstream_origin = _assert_origin(upstream_origin)
        if (
            not idempotency_record_id
            or not wallet_id
            or not permit_id
            or not public_tool_id
            or not upstream_tool_name
            or credits_authorized < 0
        ):
            raise DispatchAttemptError("dispatch_prepare_invalid")

        permits = permit_service or get_permit_service()
        factory = get_session_factory()
        try:
            async with factory() as session:
                async with session.begin():
                    record = (
                        await session.execute(
                            select(IdempotencyRecordModel)
                            .where(
                                cast(
                                    ColumnElement[bool],
                                    IdempotencyRecordModel.record_id
                                    == idempotency_record_id,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    IdempotencyRecordModel.wallet_id == wallet_id,
                                ),
                            )
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if record is None or record.request_hash != request_hash:
                        raise DispatchAttemptConflictError(
                            "dispatch_idempotency_record_invalid"
                        )
                    permit = await session.get(
                        PermitModel,
                        permit_id,
                        with_for_update=True,
                    )
                    if permit is None:
                        return PermitValidation(False, "permit_not_found", None), None
                    await self._assert_approval_binding(
                        session,
                        record=record,
                        permit=permit,
                        approval_id=approval_id,
                        wallet_id=wallet_id,
                        public_tool_id=public_tool_id,
                    )
                    unsupported_constraints = _unsupported_upstream_constraints(permit)

                    existing = await self._get_by_idempotency_record(
                        session,
                        idempotency_record_id,
                    )
                    if existing is not None:
                        self._assert_prepared_match(
                            existing,
                            idempotency_record_id=idempotency_record_id,
                            wallet_id=wallet_id,
                            permit_id=permit_id,
                            approval_id=approval_id,
                            key_id=key_id,
                            public_tool_id=public_tool_id,
                            upstream_tool_name=upstream_tool_name,
                            upstream_origin=upstream_origin,
                            request_hash=request_hash,
                            credits_authorized=credits_authorized,
                        )
                        if unsupported_constraints:
                            # A row created by an older worker may already hold a
                            # reservation. Do not turn that uncertain rollout
                            # state into a new denial receipt or a remote send;
                            # the reconciler owns its terminal classification.
                            raise DispatchPrepareCommitUncertainError(
                                "dispatch_prepare_constraint_unsupported"
                            )
                        if existing.state != DISPATCH_PREPARED:
                            raise DispatchPrepareCommitUncertainError(
                                "dispatch_prepare_already_advanced"
                            )
                        replay_access = await permits.validate_replay_access(
                            permit_id=permit_id,
                            wallet_id=wallet_id,
                            tool_name=public_tool_id,
                            key_id=key_id,
                            session=session,
                        )
                        return replay_access, existing

                    validation = await permits._validate_model_for_action(
                        session=session,
                        model=permit,
                        wallet_id=wallet_id,
                        tool_name=public_tool_id,
                        estimated_credits=credits_authorized,
                        key_id=key_id,
                        arguments=arguments,
                    )
                    if not validation.allowed:
                        return validation, None
                    if unsupported_constraints:
                        # The remote path atomically enforces max_credits below,
                        # but it does not yet reserve per-tool call slots or fold
                        # in-flight reservations into aggregate_value_cap. A
                        # read-time check would let concurrent calls overshoot;
                        # refuse the constrained permit before creating any
                        # attempt or moving budget instead.
                        return (
                            PermitValidation(
                                False,
                                "permit_constraint_unsupported_for_upstream",
                                permit,
                                {
                                    "execution_backend": "upstream_mcp",
                                    "unsupported_constraints": unsupported_constraints,
                                },
                            ),
                            None,
                        )

                    # Reserve with the same guarded UPDATE that
                    # PermitService.authorize_and_reserve() uses. The cap
                    # predicate is evaluated by the database as part of the
                    # statement that performs the increment, so two concurrent
                    # reservations cannot both pass even on SQLite, where the
                    # FOR UPDATE above is a silent no-op. A read-modify-write
                    # here would lose an increment on that engine and overspend
                    # the permit -- the bug fixed for the local path in 25897fd,
                    # which this upstream path did not inherit. The
                    # read-validated numbers are advisory; this write is the
                    # authority.
                    #
                    # Expiry is in the predicate for the same reason the cap is.
                    # An expired permit keeps status="active" in storage, so
                    # without this term a permit could pass the read-time expiry
                    # check, cross expires_at, and still be reserved against.
                    # One `now` is used for both the predicate and the denial
                    # classification below, so the two cannot disagree.
                    now = utc_now()
                    reserved = await session.execute(
                        sa_update(PermitModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitModel.permit_id == permit_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                PermitModel.status == "active",
                            ),
                            cast(
                                ColumnElement[bool],
                                PermitModel.expires_at > now,
                            ),
                            cast(
                                ColumnElement[bool],
                                PermitModel.spent_credits + credits_authorized
                                <= PermitModel.max_credits,
                            ),
                        )
                        .values(
                            spent_credits=PermitModel.spent_credits
                            + credits_authorized,
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if (cast(Any, reserved).rowcount or 0) != 1:
                        # A concurrent reservation consumed the remaining budget,
                        # or a concurrent revocation flipped the status, between
                        # the validation read and this guarded write. Deny with
                        # an accurate reason and create no prepared attempt --
                        # no budget moved, so there is nothing to compensate.
                        await session.refresh(permit)
                        if permit.status != "active":
                            return (
                                PermitValidation(
                                    False,
                                    f"permit_{permit.status}",
                                    permit,
                                    {"status": permit.status},
                                ),
                                None,
                            )
                        # Reachable now that expiry is in the predicate above.
                        # Classified before budget so a permit that expired
                        # mid-flight is not misreported as out of money.
                        if to_naive_utc(permit.expires_at) <= now:
                            return (
                                PermitValidation(
                                    False,
                                    "permit_expired",
                                    permit,
                                    {
                                        "expired_at": to_naive_utc(
                                            permit.expires_at
                                        ).isoformat(),
                                        "checked_at": now.isoformat(),
                                    },
                                ),
                                None,
                            )
                        return (
                            PermitValidation(
                                False,
                                "permit_budget_exceeded",
                                permit,
                                {
                                    "required_credits": format(credits_authorized, "f"),
                                    "remaining_credits": format(
                                        permit.max_credits - permit.spent_credits,
                                        "f",
                                    ),
                                    "spent_credits": format(permit.spent_credits, "f"),
                                    "max_credits": format(permit.max_credits, "f"),
                                },
                            ),
                            None,
                        )
                    # Reflect the committed reservation on the returned model.
                    await session.refresh(permit)
                    attempt = McpDispatchAttemptModel(
                        attempt_id=f"dsp-{uuid.uuid4().hex[:16]}",
                        idempotency_record_id=idempotency_record_id,
                        wallet_id=wallet_id,
                        permit_id=permit_id,
                        approval_id=approval_id,
                        key_id=key_id,
                        public_tool_id=public_tool_id,
                        upstream_tool_name=upstream_tool_name,
                        upstream_origin=upstream_origin,
                        request_hash=request_hash,
                        credits_authorized=credits_authorized,
                        state=DISPATCH_PREPARED,
                    )
                    session.add(attempt)
                    await session.flush()
                return validation, attempt
        except DispatchAttemptError:
            raise
        except Exception as exc:
            # A database driver can report a failed COMMIT after the server
            # durably applied it. Adopt only the exact prepared identity; a
            # normal rollback leaves no row. If the recovery read itself fails,
            # the outcome is unknown and callers must not compensate it.
            try:
                async with factory() as recovery_session:
                    existing = await self._get_by_idempotency_record(
                        recovery_session,
                        idempotency_record_id,
                    )
                    if existing is not None:
                        record = await recovery_session.get(
                            IdempotencyRecordModel,
                            idempotency_record_id,
                        )
                        permit = await recovery_session.get(PermitModel, permit_id)
                        if (
                            record is None
                            or record.wallet_id != wallet_id
                            or record.request_hash != request_hash
                            or permit is None
                        ):
                            raise DispatchPrepareCommitUncertainError(
                                "dispatch_prepare_commit_uncertain"
                            )
                        await self._assert_approval_binding(
                            recovery_session,
                            record=record,
                            permit=permit,
                            approval_id=approval_id,
                            wallet_id=wallet_id,
                            public_tool_id=public_tool_id,
                        )
                        if _unsupported_upstream_constraints(permit):
                            # A row created by an older worker may already hold a
                            # reservation the atomic path cannot re-validate.
                            # Keep it commit-uncertain so the reconciler owns
                            # its terminal classification instead of adopting it
                            # here as a clean success or a new denial.
                            raise DispatchPrepareCommitUncertainError(
                                "dispatch_prepare_constraint_unsupported"
                            )
            except DispatchPrepareCommitUncertainError:
                raise
            except Exception as recovery_exc:
                raise DispatchPrepareCommitUncertainError(
                    "dispatch_prepare_commit_uncertain"
                ) from recovery_exc
            if existing is None:
                raise DispatchPrepareRolledBackError(
                    "dispatch_prepare_rolled_back"
                ) from exc
            try:
                self._assert_prepared_match(
                    existing,
                    idempotency_record_id=idempotency_record_id,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    approval_id=approval_id,
                    key_id=key_id,
                    public_tool_id=public_tool_id,
                    upstream_tool_name=upstream_tool_name,
                    upstream_origin=upstream_origin,
                    request_hash=request_hash,
                    credits_authorized=credits_authorized,
                )
            except DispatchAttemptError as invariant_exc:
                raise DispatchPrepareCommitUncertainError(
                    "dispatch_prepare_commit_uncertain"
                ) from invariant_exc
            if existing.state != DISPATCH_PREPARED:
                raise DispatchPrepareCommitUncertainError(
                    "dispatch_prepare_commit_uncertain"
                )
            try:
                replay_access = await permits.validate_replay_access(
                    permit_id=permit_id,
                    wallet_id=wallet_id,
                    tool_name=public_tool_id,
                    key_id=key_id,
                )
            except Exception as replay_exc:
                raise DispatchPrepareCommitUncertainError(
                    "dispatch_prepare_commit_uncertain"
                ) from replay_exc
            if not replay_access.allowed:
                raise DispatchPrepareCommitUncertainError(
                    "dispatch_prepare_commit_uncertain"
                )
            return replay_access, existing

    async def attach_charge(
        self,
        *,
        attempt_id: str,
        ledger_entry_id: str,
        credits_charged: Decimal,
    ) -> McpDispatchAttemptModel:
        if credits_charged < 0:
            raise DispatchAttemptError("dispatch_charge_invalid")
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                attempt = await session.get(
                    McpDispatchAttemptModel,
                    attempt_id,
                    with_for_update=True,
                )
                if attempt is None:
                    raise DispatchAttemptError("dispatch_attempt_not_found")
                if attempt.ledger_entry_id is not None:
                    if (
                        attempt.ledger_entry_id != ledger_entry_id
                        or attempt.credits_charged != credits_charged
                    ):
                        raise DispatchAttemptConflictError("dispatch_charge_conflict")
                    return attempt
                if attempt.state != DISPATCH_PREPARED:
                    raise DispatchAttemptConflictError(
                        "dispatch_charge_transition_invalid"
                    )

                ledger = await session.get(LedgerEntryModel, ledger_entry_id)
                if (
                    ledger is None
                    or ledger.wallet_id != attempt.wallet_id
                    or ledger.action != "debit"
                    or ledger.operation_key != attempt.idempotency_record_id
                    or ledger.amount != -credits_charged
                ):
                    raise DispatchAttemptConflictError(
                        "dispatch_ledger_linkage_invalid"
                    )
                attempt.ledger_entry_id = ledger_entry_id
                attempt.credits_charged = credits_charged
                attempt.updated_at = utc_now()
                session.add(attempt)
                return attempt

    async def abandon_effect_free_prepared_attempt(
        self,
        *,
        attempt_id: str,
        expected_updated_at: datetime,
    ) -> None:
        """Atomically remove an unclaimed, uncharged attempt and its reservation.

        This is the narrow escape hatch for a pre-dispatch condition whose
        public contract predates durable dispatch attempts (currently a lost
        quote-consumption race). Deleting the attempt is safe only while no
        charge or send authority exists. The permit decrement and deletion
        share one transaction, so reconciliation can never observe a prepared
        row whose reservation was already released.
        """

        if not attempt_id:
            raise DispatchAttemptError("dispatch_attempt_invalid")
        factory = get_session_factory()
        try:
            async with factory() as session:
                async with session.begin():
                    # Acquire a SQLite writer transaction before inspecting the
                    # row. PostgreSQL additionally protects it with FOR UPDATE.
                    await session.execute(
                        sa_update(McpDispatchAttemptModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                McpDispatchAttemptModel.attempt_id == attempt_id,
                            )
                        )
                        .values(state=McpDispatchAttemptModel.state)
                        .execution_options(synchronize_session=False)
                    )
                    attempt = await session.get(
                        McpDispatchAttemptModel,
                        attempt_id,
                        with_for_update=True,
                    )
                    if attempt is None:
                        raise DispatchAttemptConflictError("dispatch_attempt_not_found")
                    if (
                        attempt.state != DISPATCH_PREPARED
                        or attempt.updated_at != expected_updated_at
                        or attempt.dispatch_claim_hash is not None
                        or attempt.dispatched_at is not None
                        or attempt.ledger_entry_id is not None
                        or attempt.credits_charged != Decimal("0")
                        or attempt.completed_at is not None
                        or attempt.debit_refunded_at is not None
                        or attempt.budget_released_at is not None
                    ):
                        raise DispatchClaimUnavailableError("dispatch_attempt_advanced")

                    record = await session.get(
                        IdempotencyRecordModel,
                        attempt.idempotency_record_id,
                        with_for_update=True,
                    )
                    if record is None or record.ledger_entry_id is not None:
                        raise DispatchClaimUnavailableError("dispatch_attempt_advanced")
                    operation_debit = (
                        await session.execute(
                            select(LedgerEntryModel).where(
                                cast(
                                    ColumnElement[bool],
                                    LedgerEntryModel.wallet_id == attempt.wallet_id,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    LedgerEntryModel.operation_key
                                    == attempt.idempotency_record_id,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    LedgerEntryModel.action == "debit",
                                ),
                            )
                        )
                    ).scalar_one_or_none()
                    if operation_debit is not None:
                        raise DispatchClaimUnavailableError("dispatch_attempt_advanced")
                    linked_receipt = (
                        await session.execute(
                            select(ReceiptModel).where(
                                cast(
                                    ColumnElement[bool],
                                    ReceiptModel.dispatch_attempt_id == attempt_id,
                                )
                            )
                        )
                    ).scalar_one_or_none()
                    if linked_receipt is not None:
                        raise DispatchClaimUnavailableError("dispatch_attempt_advanced")

                    released = await session.execute(
                        sa_update(PermitModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitModel.permit_id == attempt.permit_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                PermitModel.spent_credits >= attempt.credits_authorized,
                            ),
                        )
                        .values(
                            spent_credits=PermitModel.spent_credits
                            - attempt.credits_authorized,
                            updated_at=utc_now(),
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if (cast(Any, released).rowcount or 0) != 1:
                        raise DispatchAttemptConflictError(
                            "dispatch_budget_release_invalid"
                        )
                    await session.delete(attempt)
                    await session.flush()
        except DispatchAttemptError:
            raise
        except Exception as exc:
            # A failed COMMIT acknowledgement is safe to adopt only when the
            # exact attempt is gone. If it remains or the recovery read fails,
            # leave the idempotency record in progress and let reconciliation
            # classify the durable row; never emit the legacy denial response.
            try:
                async with factory() as recovery_session:
                    recovered = await recovery_session.get(
                        McpDispatchAttemptModel,
                        attempt_id,
                    )
            except Exception as recovery_exc:
                raise DispatchClaimUnavailableError(
                    "dispatch_abandon_commit_uncertain"
                ) from recovery_exc
            if recovered is None:
                return
            raise DispatchClaimUnavailableError(
                "dispatch_abandon_commit_uncertain"
            ) from exc

    async def claim_dispatch(self, attempt_id: str) -> McpDispatchAttemptModel:
        """Acquire the durable, non-reacquirable right to send exactly once.

        Every activation generates a fresh process-local secret and persists
        only its hash. A later activation can never adopt an existing claim.
        If the database commits but its acknowledgement is lost, this still-
        live call may recover only the row carrying its own generated hash.
        """
        claim_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        factory = get_session_factory()
        claim_written = False
        try:
            async with factory() as session:
                async with session.begin():
                    observed = await session.get(
                        McpDispatchAttemptModel,
                        attempt_id,
                        with_for_update=True,
                    )
                    if observed is None:
                        raise DispatchAttemptError("dispatch_attempt_not_found")
                    if (
                        observed.state == DISPATCH_PREPARED
                        and observed.dispatch_claim_hash is None
                        and observed.dispatched_at is None
                        and not await _claim_debit_is_valid(session, observed)
                    ):
                        raise DispatchAttemptConflictError(
                            "dispatch_claim_evidence_invalid"
                        )
                    now = utc_now()
                    claimed = await session.execute(
                        sa_update(McpDispatchAttemptModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                McpDispatchAttemptModel.attempt_id == attempt_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                McpDispatchAttemptModel.state == DISPATCH_PREPARED,
                            ),
                            cast(
                                ColumnElement[bool],
                                cast(
                                    Any,
                                    McpDispatchAttemptModel.dispatch_claim_hash,
                                ).is_(None),
                            ),
                            cast(
                                ColumnElement[bool],
                                cast(
                                    Any,
                                    McpDispatchAttemptModel.ledger_entry_id,
                                ).is_not(None),
                            ),
                            cast(
                                ColumnElement[bool],
                                cast(
                                    Any,
                                    McpDispatchAttemptModel.dispatched_at,
                                ).is_(None),
                            ),
                        )
                        .values(
                            state=DISPATCH_CLAIMED,
                            dispatch_claim_hash=claim_hash,
                            dispatched_at=now,
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if cast(Any, claimed).rowcount == 1:
                        claim_written = True
                    await session.refresh(observed)
                    attempt = observed
                    if claim_written:
                        return attempt
                    if attempt.state in DISPATCH_TERMINAL_STATES:
                        raise DispatchClaimUnavailableError(
                            "dispatch_transition_terminal"
                        )
                    if (
                        attempt.state in DISPATCH_SENT_STATES
                        or attempt.dispatch_claim_hash is not None
                        or attempt.dispatched_at is not None
                    ):
                        raise DispatchClaimUnavailableError(
                            "dispatch_claim_unavailable"
                        )
                    raise DispatchAttemptConflictError("dispatch_transition_invalid")
        except Exception:
            if not claim_written:
                raise
            # A driver can report a failed COMMIT after the database durably
            # applied it. Only this still-live activation knows the generated
            # hash, so only it may adopt that uncertain acknowledgement.
            async with factory() as recovery_session:
                recovered = await recovery_session.get(
                    McpDispatchAttemptModel,
                    attempt_id,
                )
                recovered_debit_valid = bool(
                    recovered is not None
                    and await _claim_debit_is_valid(recovery_session, recovered)
                )
            if (
                recovered is not None
                and recovered.state == DISPATCH_CLAIMED
                and recovered.dispatch_claim_hash == claim_hash
                and recovered_debit_valid
            ):
                return recovered
            raise

    async def complete_pre_dispatch_failure(
        self,
        *,
        attempt_id: str,
        expected_updated_at: datetime,
        ledger_entry_id: str | None = None,
        credits_charged: Decimal | None = None,
        result_payload: dict[str, Any] | None,
        error_code: str | None,
        max_result_bytes: int,
    ) -> McpDispatchAttemptModel:
        """Terminalize only while the one-shot send authority is unclaimed."""
        result_json, result_size_bytes, response_hash = _validated_terminal_result(
            state="returned_error",
            result_payload=result_payload,
            error_code=error_code,
            max_result_bytes=max_result_bytes,
        )
        if (ledger_entry_id is None) != (credits_charged is None):
            raise DispatchAttemptError("dispatch_charge_linkage_incomplete")
        if credits_charged is not None and credits_charged < 0:
            raise DispatchAttemptError("dispatch_charge_invalid")
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                # Acquire the same write fence used before a fresh debit. The
                # no-op UPDATE starts a SQLite writer transaction before reads.
                await session.execute(
                    sa_update(McpDispatchAttemptModel)
                    .where(
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.attempt_id == attempt_id,
                        )
                    )
                    .values(state=McpDispatchAttemptModel.state)
                    .execution_options(synchronize_session=False)
                )
                observed = await session.get(McpDispatchAttemptModel, attempt_id)
                if observed is None:
                    raise DispatchAttemptError("dispatch_attempt_not_found")

                operation_debit = (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            cast(
                                ColumnElement[bool],
                                LedgerEntryModel.wallet_id == observed.wallet_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                LedgerEntryModel.operation_key
                                == observed.idempotency_record_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                LedgerEntryModel.action == "debit",
                            ),
                        )
                    )
                ).scalar_one_or_none()
                if operation_debit is not None:
                    if (
                        operation_debit.amount >= 0
                        or ledger_entry_id not in {None, operation_debit.entry_id}
                        or credits_charged not in {None, -operation_debit.amount}
                    ):
                        raise DispatchAttemptConflictError(
                            "dispatch_ledger_linkage_invalid"
                        )
                    ledger_entry_id = operation_debit.entry_id
                    credits_charged = -operation_debit.amount
                if ledger_entry_id is not None and credits_charged is not None:
                    if observed.ledger_entry_id not in {None, ledger_entry_id}:
                        raise DispatchAttemptConflictError("dispatch_charge_conflict")
                    ledger = await session.get(LedgerEntryModel, ledger_entry_id)
                    if (
                        ledger is None
                        or ledger.wallet_id != observed.wallet_id
                        or ledger.action != "debit"
                        or ledger.operation_key != observed.idempotency_record_id
                        or ledger.amount != -credits_charged
                    ):
                        raise DispatchAttemptConflictError(
                            "dispatch_ledger_linkage_invalid"
                        )

                now = utc_now()
                values: dict[str, Any] = {
                    "state": "returned_error",
                    "result_json": result_json,
                    "result_size_bytes": result_size_bytes,
                    "response_hash": response_hash,
                    "error_code": error_code,
                    "updated_at": now,
                    "completed_at": now,
                }
                if ledger_entry_id is not None and credits_charged is not None:
                    values["ledger_entry_id"] = ledger_entry_id
                    values["credits_charged"] = credits_charged
                completed = await session.execute(
                    sa_update(McpDispatchAttemptModel)
                    .where(
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.attempt_id == attempt_id,
                        ),
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.state == DISPATCH_PREPARED,
                        ),
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.updated_at == expected_updated_at,
                        ),
                        cast(
                            ColumnElement[bool],
                            cast(
                                Any,
                                McpDispatchAttemptModel.dispatch_claim_hash,
                            ).is_(None),
                        ),
                        cast(
                            ColumnElement[bool],
                            cast(
                                Any,
                                McpDispatchAttemptModel.dispatched_at,
                            ).is_(None),
                        ),
                    )
                    .values(**values)
                )
                transitioned = cast(Any, completed).rowcount == 1
                await session.refresh(observed)
                attempt = observed
                if transitioned:
                    return attempt
                if (
                    attempt.state in DISPATCH_SENT_STATES
                    or attempt.dispatch_claim_hash is not None
                    or attempt.dispatched_at is not None
                ):
                    raise DispatchClaimUnavailableError("dispatch_claim_unavailable")
                if attempt.state in DISPATCH_TERMINAL_STATES:
                    if (
                        attempt.state != "returned_error"
                        or attempt.result_json != result_json
                        or attempt.result_size_bytes != result_size_bytes
                        or attempt.response_hash != response_hash
                        or attempt.error_code != error_code
                    ):
                        raise DispatchAttemptConflictError("dispatch_terminal_conflict")
                    return attempt
                if (
                    attempt.state == DISPATCH_PREPARED
                    and attempt.dispatch_claim_hash is None
                    and attempt.updated_at != expected_updated_at
                ):
                    raise DispatchClaimUnavailableError("dispatch_attempt_advanced")
                raise DispatchAttemptConflictError(
                    "dispatch_terminal_transition_invalid"
                )

    async def mark_debit_refunded(
        self,
        *,
        attempt_id: str,
        ledger_entry_id: str,
    ) -> McpDispatchAttemptModel:
        """Checkpoint an idempotent refund after its ledger row is durable."""
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                attempt = await session.get(
                    McpDispatchAttemptModel,
                    attempt_id,
                    with_for_update=True,
                )
                if attempt is None:
                    raise DispatchAttemptError("dispatch_attempt_not_found")
                if attempt.ledger_entry_id != ledger_entry_id:
                    raise DispatchAttemptConflictError(
                        "dispatch_refund_ledger_conflict"
                    )
                if attempt.state != "returned_error":
                    raise DispatchAttemptConflictError("dispatch_refund_state_invalid")
                refund = (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            cast(
                                ColumnElement[bool],
                                LedgerEntryModel.wallet_id == attempt.wallet_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                LedgerEntryModel.action == "refund",
                            ),
                            cast(
                                ColumnElement[bool],
                                LedgerEntryModel.correlation_id == ledger_entry_id,
                            ),
                        )
                    )
                ).scalar_one_or_none()
                if refund is None:
                    raise DispatchAttemptConflictError("dispatch_refund_not_durable")
                if attempt.debit_refunded_at is None:
                    now = utc_now()
                    attempt.debit_refunded_at = now
                    attempt.updated_at = now
                    session.add(attempt)
                return attempt

    async def complete(
        self,
        *,
        attempt_id: str,
        state: str,
        result_payload: dict[str, Any] | None,
        error_code: str | None,
        max_result_bytes: int,
    ) -> McpDispatchAttemptModel:
        result_json, result_size_bytes, response_hash = _validated_terminal_result(
            state=state,
            result_payload=result_payload,
            error_code=error_code,
            max_result_bytes=max_result_bytes,
        )

        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                # Acquire the SQLite writer transaction before the terminal
                # read-modify-write. FOR UPDATE alone is a silent no-op on
                # SQLite, so a live success finalizer and the stale-claim
                # reconciler could otherwise both observe dispatch_claimed and
                # persist conflicting terminal states. PostgreSQL additionally
                # protects the row with FOR UPDATE below.
                await session.execute(
                    sa_update(McpDispatchAttemptModel)
                    .where(
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.attempt_id == attempt_id,
                        )
                    )
                    .values(state=McpDispatchAttemptModel.state)
                    .execution_options(synchronize_session=False)
                )
                attempt = await session.get(
                    McpDispatchAttemptModel,
                    attempt_id,
                    with_for_update=True,
                )
                if attempt is None:
                    raise DispatchAttemptError("dispatch_attempt_not_found")
                if attempt.state in DISPATCH_TERMINAL_STATES:
                    if (
                        attempt.state != state
                        or attempt.result_json != result_json
                        or attempt.result_size_bytes != result_size_bytes
                        or attempt.response_hash != response_hash
                        or attempt.error_code != error_code
                    ):
                        raise DispatchAttemptConflictError("dispatch_terminal_conflict")
                    return attempt

                if attempt.state == DISPATCH_CLAIMED:
                    claim_hash = attempt.dispatch_claim_hash
                    if (
                        claim_hash is None
                        or len(claim_hash) != 64
                        or any(char not in "0123456789abcdef" for char in claim_hash)
                        or attempt.dispatched_at is None
                        or attempt.ledger_entry_id is None
                        or attempt.credits_charged <= 0
                    ):
                        raise DispatchAttemptConflictError(
                            "dispatch_claim_evidence_invalid"
                        )
                    if not await _claim_debit_is_valid(session, attempt):
                        raise DispatchAttemptConflictError(
                            "dispatch_claim_evidence_invalid"
                        )

                valid_transition = attempt.state == DISPATCH_CLAIMED or (
                    attempt.state == DISPATCH_LEGACY_DISPATCHED
                    and state == "delivery_uncertain"
                )
                if not valid_transition:
                    raise DispatchAttemptConflictError(
                        "dispatch_terminal_transition_invalid"
                    )
                now = utc_now()
                attempt.state = state
                attempt.result_json = result_json
                attempt.result_size_bytes = result_size_bytes
                attempt.response_hash = response_hash
                attempt.error_code = error_code
                attempt.updated_at = now
                attempt.completed_at = now
                session.add(attempt)
                return attempt

    async def get_context(self, attempt_id: str) -> DispatchAttemptContext | None:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(McpDispatchAttemptModel, IdempotencyRecordModel)
                    .join(
                        IdempotencyRecordModel,
                        cast(
                            ColumnElement[bool],
                            IdempotencyRecordModel.record_id
                            == McpDispatchAttemptModel.idempotency_record_id,
                        ),
                    )
                    .where(
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.attempt_id == attempt_id,
                        )
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            attempt, record = row
            permit = await session.get(PermitModel, attempt.permit_id)
            if permit is None:
                raise DispatchAttemptConflictError("dispatch_permit_not_found")
            # Re-check durable approval evidence before a crash reconciler can
            # use the attempt as authority for a newly signed audit or receipt.
            # The prepare-time check prevents bad service writes; this read-time
            # check fails closed on later corruption or out-of-band updates.
            await self._assert_approval_binding(
                session,
                record=record,
                permit=permit,
                approval_id=attempt.approval_id,
                wallet_id=attempt.wallet_id,
                public_tool_id=attempt.public_tool_id,
            )
            return DispatchAttemptContext(
                attempt=attempt,
                endpoint=record.endpoint,
                idempotency_key=record.idempotency_key,
            )

    async def list_stale_contexts(
        self,
        *,
        idle_seconds: int = 300,
        limit: int = 100,
    ) -> list[DispatchAttemptContext]:
        if idle_seconds < 0 or not 1 <= limit <= 500:
            raise DispatchAttemptError("dispatch_reconciliation_query_invalid")
        cutoff = utc_now() - timedelta(seconds=idle_seconds)
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(McpDispatchAttemptModel, IdempotencyRecordModel)
                    .join(
                        IdempotencyRecordModel,
                        cast(
                            ColumnElement[bool],
                            IdempotencyRecordModel.record_id
                            == McpDispatchAttemptModel.idempotency_record_id,
                        ),
                    )
                    .where(
                        cast(
                            ColumnElement[bool],
                            cast(Any, McpDispatchAttemptModel.state).in_(
                                DISPATCH_ACTIVE_STATES
                            ),
                        ),
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.updated_at < cutoff,
                        ),
                    )
                    .order_by(
                        cast(ColumnElement[Any], McpDispatchAttemptModel.updated_at)
                    )
                    .limit(limit)
                )
            ).all()
        return [
            DispatchAttemptContext(
                attempt=attempt,
                endpoint=record.endpoint,
                idempotency_key=record.idempotency_key,
            )
            for attempt, record in rows
        ]

    async def list_unfinalized_terminal_contexts(
        self,
        *,
        idle_seconds: int = 300,
        limit: int = 100,
    ) -> list[DispatchAttemptContext]:
        """Return terminal attempts whose signed receipt was never persisted."""
        if idle_seconds < 0 or not 1 <= limit <= 500:
            raise DispatchAttemptError("dispatch_reconciliation_query_invalid")
        cutoff = utc_now() - timedelta(seconds=idle_seconds)
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(McpDispatchAttemptModel, IdempotencyRecordModel)
                    .join(
                        IdempotencyRecordModel,
                        cast(
                            ColumnElement[bool],
                            IdempotencyRecordModel.record_id
                            == McpDispatchAttemptModel.idempotency_record_id,
                        ),
                    )
                    .outerjoin(
                        ReceiptModel,
                        cast(
                            ColumnElement[bool],
                            ReceiptModel.dispatch_attempt_id
                            == McpDispatchAttemptModel.attempt_id,
                        ),
                    )
                    .where(
                        cast(
                            ColumnElement[bool],
                            cast(Any, McpDispatchAttemptModel.state).in_(
                                DISPATCH_TERMINAL_STATES
                            ),
                        ),
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.updated_at < cutoff,
                        ),
                        cast(
                            ColumnElement[bool],
                            cast(Any, ReceiptModel.receipt_id).is_(None),
                        ),
                    )
                    .order_by(
                        cast(ColumnElement[Any], McpDispatchAttemptModel.updated_at)
                    )
                    .limit(limit)
                )
            ).all()
        return [
            DispatchAttemptContext(
                attempt=attempt,
                endpoint=record.endpoint,
                idempotency_key=record.idempotency_key,
            )
            for attempt, record in rows
        ]

    async def list_idempotency_incomplete_terminal_contexts(
        self,
        *,
        idle_seconds: int = 300,
        limit: int = 100,
    ) -> list[DispatchAttemptContext]:
        """Return receipted terminal attempts missing replay completion."""
        if idle_seconds < 0 or not 1 <= limit <= 500:
            raise DispatchAttemptError("dispatch_reconciliation_query_invalid")
        cutoff = utc_now() - timedelta(seconds=idle_seconds)
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(McpDispatchAttemptModel, IdempotencyRecordModel)
                    .join(
                        IdempotencyRecordModel,
                        cast(
                            ColumnElement[bool],
                            IdempotencyRecordModel.record_id
                            == McpDispatchAttemptModel.idempotency_record_id,
                        ),
                    )
                    .join(
                        ReceiptModel,
                        cast(
                            ColumnElement[bool],
                            ReceiptModel.dispatch_attempt_id
                            == McpDispatchAttemptModel.attempt_id,
                        ),
                    )
                    .where(
                        cast(
                            ColumnElement[bool],
                            cast(Any, McpDispatchAttemptModel.state).in_(
                                DISPATCH_TERMINAL_STATES
                            ),
                        ),
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.updated_at < cutoff,
                        ),
                        cast(
                            ColumnElement[bool],
                            cast(Any, IdempotencyRecordModel.response_json).is_(None),
                        ),
                    )
                    .order_by(
                        cast(ColumnElement[Any], McpDispatchAttemptModel.updated_at)
                    )
                    .limit(limit)
                )
            ).all()
        return [
            DispatchAttemptContext(
                attempt=attempt,
                endpoint=record.endpoint,
                idempotency_key=record.idempotency_key,
            )
            for attempt, record in rows
        ]

    async def summarize(
        self,
        *,
        idle_seconds: int = 300,
        terminal_idle_seconds: int | None = None,
    ) -> DispatchAttemptMetrics:
        """Return state counts and reconciliation backlog without payloads."""
        terminal_idle = (
            idle_seconds if terminal_idle_seconds is None else terminal_idle_seconds
        )
        if idle_seconds < 0 or terminal_idle < 0:
            raise DispatchAttemptError("dispatch_reconciliation_query_invalid")
        active_cutoff = utc_now() - timedelta(seconds=idle_seconds)
        terminal_cutoff = utc_now() - timedelta(seconds=terminal_idle)
        factory = get_session_factory()
        async with factory() as session:
            state_rows = (
                await session.execute(
                    select(
                        cast(Any, McpDispatchAttemptModel.state),
                        func.count(),
                    ).group_by(cast(Any, McpDispatchAttemptModel.state))
                )
            ).all()
            stale_active = await session.scalar(
                select(func.count())
                .select_from(McpDispatchAttemptModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        cast(Any, McpDispatchAttemptModel.state).in_(
                            DISPATCH_ACTIVE_STATES
                        ),
                    ),
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.updated_at < active_cutoff,
                    ),
                )
            )
            unfinalized_terminal = await session.scalar(
                select(func.count())
                .select_from(McpDispatchAttemptModel)
                .outerjoin(
                    ReceiptModel,
                    cast(
                        ColumnElement[bool],
                        ReceiptModel.dispatch_attempt_id
                        == McpDispatchAttemptModel.attempt_id,
                    ),
                )
                .where(
                    cast(
                        ColumnElement[bool],
                        cast(Any, McpDispatchAttemptModel.state).in_(
                            DISPATCH_TERMINAL_STATES
                        ),
                    ),
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.updated_at < terminal_cutoff,
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, ReceiptModel.receipt_id).is_(None),
                    ),
                )
            )
            terminal_idempotency_incomplete = await session.scalar(
                select(func.count())
                .select_from(McpDispatchAttemptModel)
                .join(
                    IdempotencyRecordModel,
                    cast(
                        ColumnElement[bool],
                        IdempotencyRecordModel.record_id
                        == McpDispatchAttemptModel.idempotency_record_id,
                    ),
                )
                .join(
                    ReceiptModel,
                    cast(
                        ColumnElement[bool],
                        ReceiptModel.dispatch_attempt_id
                        == McpDispatchAttemptModel.attempt_id,
                    ),
                )
                .where(
                    cast(
                        ColumnElement[bool],
                        cast(Any, McpDispatchAttemptModel.state).in_(
                            DISPATCH_TERMINAL_STATES
                        ),
                    ),
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.updated_at < terminal_cutoff,
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, IdempotencyRecordModel.response_json).is_(None),
                    ),
                )
            )
        return DispatchAttemptMetrics(
            state_counts={str(state): int(count) for state, count in state_rows},
            stale_active=int(stale_active or 0),
            unfinalized_terminal=int(unfinalized_terminal or 0),
            terminal_idempotency_incomplete=int(terminal_idempotency_incomplete or 0),
        )


_service: McpDispatchAttemptService | None = None


def get_mcp_dispatch_attempt_service() -> McpDispatchAttemptService:
    global _service
    if _service is None:
        _service = McpDispatchAttemptService()
    return _service
