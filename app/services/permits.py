from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import case, func, or_, select, update as sa_update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    BillingAlertModel,
    IdempotencyRecordModel,
    McpDispatchAttemptModel,
    PermitCallReservationModel,
    PermitModel,
    ReceiptModel,
    WalletModel,
)
from app.schemas.trust import PermitCreateRequest, PermitResponse
from app.services.signing_keys import get_signing_key_service


class PermitError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PermitValidation:
    """Verdict on one governed action, with the numbers behind a denial.

    ``reason`` names what failed; ``details`` says by how much. An agent that
    is told only ``permit_budget_exceeded`` can do nothing but retry and fail
    again — the same denial with ``{"required": 50, "remaining": 12}`` tells it
    what permit to ask for. Details describe the caller's own permit, so they
    disclose nothing the permit holder cannot already read.
    """

    allowed: bool
    reason: str | None
    permit: PermitModel | None
    details: dict[str, Any] | None = None


def _num(value: Decimal | None) -> str | None:
    """Render a credit amount as an exact decimal string for a JSON payload."""
    return None if value is None else str(value)


def _stamp(value: datetime | None) -> str | None:
    """Render a naive-UTC column value as an explicit UTC timestamp."""
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"


# Every ``spent_credits`` mutation is applied as a single guarded UPDATE rather
# than a read-modify-write, so the permit cap is enforced atomically at the row
# level. ``SELECT ... FOR UPDATE`` is a silent no-op on SQLite, so without this
# two concurrent reservations both read the same ``spent_credits``, both pass the
# cap check, and their increments clobber each other (a lost update) — the exact
# over-spend this closes. Under genuine concurrency SQLite's WAL raises a
# transient "database is locked"/"snapshot" conflict on the second writer; we
# retry that with a small backoff. On PostgreSQL the row lock blocks instead of
# raising, so the retry never triggers there.
_PERMIT_WRITE_MAX_ATTEMPTS = 40


def _is_retryable_write_conflict(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "locked" in message or "snapshot" in message


def _loads_list(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def _loads_dict(value: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def permit_constraints_snapshot(permit_model: Any) -> dict[str, Any]:
    """Build the permit v2 ``constraints_evaluated`` snapshot for receipt signing.

    This is the single source of the snapshot's byte representation. The live
    invoke path and the crash reconciler both sign receipts containing it, so
    they must format identically — ``aggregate_value_cap`` in particular is
    normalized (``Decimal("10.00")`` → ``"10"``) so a receipt minted during
    crash recovery hashes the same constraints a live receipt would.
    """

    ce: dict[str, Any] = {}
    max_calls = _loads_dict(permit_model.max_calls_per_tool_json or "{}")
    if max_calls:
        ce["max_calls_per_tool"] = max_calls
    if permit_model.aggregate_value_cap is not None:
        ce["aggregate_value_cap"] = format(
            permit_model.aggregate_value_cap.normalize(), "f"
        )
    forbidden = _loads_list(permit_model.forbidden_fields_json or "[]")
    if forbidden:
        ce["forbidden_fields"] = forbidden
    if permit_model.recipient_domain:
        ce["recipient_domain"] = permit_model.recipient_domain
    return ce


def _find_forbidden_field(arguments: Any, forbidden: set[str]) -> str | None:
    """Return the first forbidden key found anywhere in the argument tree.

    Walks nested dicts and lists so a forbidden key cannot be smuggled past
    the check by nesting it below the top level. Comparison is against dict
    keys only (a forbidden name appearing as a string *value* is not a match).
    """
    stack: list[Any] = [arguments]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, child in node.items():
                if key in forbidden:
                    return str(key)
                stack.append(child)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return None


def permit_model_to_response(model: PermitModel) -> PermitResponse:
    return PermitResponse(
        permit_id=model.permit_id,
        issuer_wallet_id=model.issuer_wallet_id,
        subject_wallet_id=model.subject_wallet_id,
        subject_key_id=model.subject_key_id,
        scopes=_loads_list(model.scopes_json),
        allowed_tools=_loads_list(model.allowed_tools_json),
        max_credits=model.max_credits,
        spent_credits=model.spent_credits,
        expires_at=model.expires_at,
        nonce=model.nonce,
        status=model.status,
        requires_human_approval=model.requires_human_approval,
        signature=model.signature,
        key_id=model.key_id,
        issued_at=model.issued_at,
        revoked_at=model.revoked_at,
        max_calls_per_tool=_loads_dict(model.max_calls_per_tool_json),
        aggregate_value_cap=model.aggregate_value_cap,
        forbidden_fields=_loads_list(model.forbidden_fields_json or "[]"),
        recipient_domain=model.recipient_domain,
    )


class PermitService:
    async def get_permit(self, permit_id: str) -> PermitResponse | None:
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            return permit_model_to_response(model) if model else None

    async def list_permits(
        self,
        *,
        wallet_id: str | None = None,
        status: str | None = None,
        subject_key_id: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        expires_after: datetime | None = None,
        expires_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PermitResponse], int]:
        stmt = select(PermitModel)
        count_stmt = select(func.count()).select_from(PermitModel)

        filters: list[ColumnElement[bool]] = []
        if wallet_id:
            filters.append(
                cast(
                    ColumnElement[bool],
                    or_(
                        cast(
                            ColumnElement[bool],
                            PermitModel.issuer_wallet_id == wallet_id,
                        ),
                        cast(
                            ColumnElement[bool],
                            PermitModel.subject_wallet_id == wallet_id,
                        ),
                    ),
                )
            )
        if status:
            filters.append(cast(ColumnElement[bool], PermitModel.status == status))
        if subject_key_id:
            filters.append(
                cast(ColumnElement[bool], PermitModel.subject_key_id == subject_key_id)
            )
        if created_after:
            created_after = to_naive_utc(created_after)
            filters.append(
                cast(ColumnElement[bool], PermitModel.issued_at >= created_after)
            )
        if created_before:
            created_before = to_naive_utc(created_before)
            filters.append(
                cast(ColumnElement[bool], PermitModel.issued_at <= created_before)
            )
        if expires_after:
            expires_after = to_naive_utc(expires_after)
            filters.append(
                cast(ColumnElement[bool], PermitModel.expires_at >= expires_after)
            )
        if expires_before:
            expires_before = to_naive_utc(expires_before)
            filters.append(
                cast(ColumnElement[bool], PermitModel.expires_at <= expires_before)
            )

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        stmt = (
            stmt.order_by(cast(ColumnElement[Any], PermitModel.issued_at).desc())
            .limit(limit)
            .offset(offset)
        )

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(stmt)
            total = await session.scalar(count_stmt)
            permits = [permit_model_to_response(model) for model in result.scalars()]
            return permits, int(total or 0)

    async def create_permit(
        self,
        request: PermitCreateRequest,
        subject_key_id: str | None = None,
        permit_id: str | None = None,
    ) -> PermitResponse:
        """Mint a signed permit.

        ``permit_id`` lets a caller that pre-allocated an identifier (the
        permit-request flow reserves one when the human is paged) mint under
        it, so a retried mint collides on the primary key instead of issuing a
        second permit carrying the same authority.
        """
        if request.max_credits <= Decimal("0"):
            raise PermitError("max_credits_must_be_positive")
        # Normalize to naive UTC before any comparison, signing, or persistence.
        # Guarantees the signed timestamp and persisted timestamp are identical
        # on every dialect (SQLite, PostgreSQL, asyncpg).
        expires_at = to_naive_utc(request.expires_at)
        now = utc_now()

        if expires_at <= now:
            raise PermitError("permit_expired_at_creation")

        if request.requires_human_approval:
            # Fail at creation rather than minting a permit every invoke of
            # which would be denied (simulated approvals are refused in
            # production-like environments; real mode needs Sentinel config).
            from app.services.human_approval import human_approval_available

            available, reason = human_approval_available()
            if not available:
                raise PermitError(reason or "human_approval_not_configured")

        scopes = request.scopes or [
            f"tool:{tool}:invoke" for tool in request.allowed_tools
        ]
        if "billing:charge" not in scopes:
            scopes = [*scopes, "billing:charge"]

        factory = get_session_factory()
        async with factory() as session:
            issuer = await session.get(WalletModel, request.issuer_wallet_id)
            subject = await session.get(WalletModel, request.subject_wallet_id)
            if not issuer:
                raise PermitError("issuer_wallet_not_found")
            if not subject:
                raise PermitError("subject_wallet_not_found")
            if subject.balance < request.max_credits:
                raise PermitError("permit_budget_exceeds_wallet_balance")

        permit_id = permit_id or f"permit-{uuid.uuid4().hex[:16]}"
        nonce = request.nonce or uuid.uuid4().hex
        # Prefer the explicitly-passed key_id (from auth context) over the
        # request body, so wallet-bound self-service permits show up in
        # /v1/me/permits queries filtered by subject_key_id.
        effective_key_id = request.subject_key_id or subject_key_id
        payload: dict[str, Any] = {
            "permit_id": permit_id,
            "issuer_wallet_id": request.issuer_wallet_id,
            "subject_wallet_id": request.subject_wallet_id,
            "subject_key_id": effective_key_id,
            "scopes": scopes,
            "allowed_tools": request.allowed_tools,
            "max_credits": request.max_credits,
            "expires_at": expires_at,
            "nonce": nonce,
            "status": "active",
            "issued_at": now,
        }
        # Signed only when set, so signatures on permits issued before this
        # field existed keep verifying (verify_signature mirrors this).
        if request.requires_human_approval:
            payload["requires_human_approval"] = True
        # Permit schema v2 constraints — signed only when non-empty/non-null
        if request.max_calls_per_tool:
            payload["max_calls_per_tool"] = request.max_calls_per_tool
        if request.aggregate_value_cap is not None:
            payload["aggregate_value_cap"] = request.aggregate_value_cap
        if request.forbidden_fields:
            payload["forbidden_fields"] = request.forbidden_fields
        if request.recipient_domain:
            payload["recipient_domain"] = request.recipient_domain
        signature, key_id, _ = await get_signing_key_service().sign_payload(payload)

        model = PermitModel(
            permit_id=permit_id,
            issuer_wallet_id=request.issuer_wallet_id,
            subject_wallet_id=request.subject_wallet_id,
            subject_key_id=effective_key_id,
            scopes_json=json.dumps(scopes),
            allowed_tools_json=json.dumps(request.allowed_tools),
            max_credits=request.max_credits,
            expires_at=expires_at,
            nonce=nonce,
            status="active",
            requires_human_approval=request.requires_human_approval,
            signature=signature,
            key_id=key_id,
            issued_at=now,
            max_calls_per_tool_json=json.dumps(request.max_calls_per_tool)
            if request.max_calls_per_tool
            else None,
            aggregate_value_cap=request.aggregate_value_cap,
            forbidden_fields_json=json.dumps(request.forbidden_fields)
            if request.forbidden_fields
            else None,
            recipient_domain=request.recipient_domain,
        )
        async with factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return permit_model_to_response(model)

    async def revoke_permit(self, permit_id: str) -> PermitResponse:
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            if not model:
                raise PermitError("permit_not_found")
            model.status = "revoked"
            model.revoked_at = utc_now()
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return permit_model_to_response(model)

    async def validate_for_action(
        self,
        *,
        permit_id: str,
        wallet_id: str,
        tool_name: str,
        estimated_credits: Decimal,
        key_id: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> PermitValidation:
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            if not model:
                return PermitValidation(False, "permit_not_found", None)
            return await self._validate_model_for_action(
                session=session,
                model=model,
                wallet_id=wallet_id,
                tool_name=tool_name,
                estimated_credits=estimated_credits,
                key_id=key_id,
                arguments=arguments,
            )

    async def validate_replay_access(
        self,
        *,
        permit_id: str,
        wallet_id: str,
        tool_name: str,
        key_id: str | None = None,
    ) -> PermitValidation:
        """Authorize access to an already-finalized governed invocation.

        Replay deliberately ignores mutable execution constraints such as
        expiry, revocation, and remaining budget: those were enforced before
        the original dispatch, and changing them must not make its evidence
        disappear. Stable wallet/key identity constraints still apply so a
        second key on the same wallet cannot retrieve a result produced under
        a key-bound permit. Tool scope is intentionally not re-evaluated: a
        signed denial for an out-of-scope tool must itself remain replayable.
        """
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            if model is None:
                return PermitValidation(False, "permit_not_found", None)
            return await self._validate_replay_model_access(
                session=session,
                model=model,
                wallet_id=wallet_id,
                key_id=key_id,
            )

    async def _validate_replay_model_access(
        self,
        *,
        session: AsyncSession | None = None,
        model: PermitModel,
        wallet_id: str,
        key_id: str | None,
    ) -> PermitValidation:
        """Check only stable permit identity for an existing reservation."""
        if model.subject_wallet_id != wallet_id:
            return PermitValidation(False, "permit_wallet_mismatch", model)
        if model.subject_key_id and model.subject_key_id != key_id:
            return PermitValidation(False, "permit_key_mismatch", model)
        if not await self.verify_signature(model, session=session):
            return PermitValidation(False, "permit_signature_invalid", model)
        return PermitValidation(True, None, model)

    async def authorize_and_reserve(
        self,
        *,
        permit_id: str,
        wallet_id: str,
        tool_name: str,
        estimated_credits: Decimal,
        key_id: str | None = None,
        arguments: dict[str, Any] | None = None,
        idempotency_record_id: str | None = None,
        request_hash: str | None = None,
    ) -> PermitValidation:
        """Atomically authorize an action and reserve its permit budget.

        For a governed local invocation, ``idempotency_record_id`` and
        ``request_hash`` bind the budget mutation to a durable call-slot row in
        the same transaction. An exact retry adopts that row before mutable
        constraints are re-evaluated and never reserves twice.
        """
        if (idempotency_record_id is None) != (request_hash is None):
            raise PermitError("permit_call_identity_incomplete")
        factory = get_session_factory()

        async def _once() -> PermitValidation:
            async with factory() as session:
                async with session.begin():
                    identity: IdempotencyRecordModel | None = None
                    if idempotency_record_id is not None:
                        identity = await session.get(
                            IdempotencyRecordModel,
                            idempotency_record_id,
                            with_for_update=True,
                        )
                        if (
                            identity is None
                            or identity.wallet_id != wallet_id
                            or identity.operation_kind != "local"
                            or identity.request_hash != request_hash
                            or identity.response_json is not None
                        ):
                            raise PermitError("permit_call_identity_invalid")

                    model = await session.get(
                        PermitModel, permit_id, with_for_update=True
                    )
                    if not model:
                        return PermitValidation(False, "permit_not_found", None)

                    if idempotency_record_id is not None:
                        existing = await session.get(
                            PermitCallReservationModel,
                            idempotency_record_id,
                            with_for_update=True,
                        )
                        if existing is not None:
                            if (
                                existing.wallet_id != wallet_id
                                or existing.permit_id != permit_id
                                or existing.tool != tool_name
                                or existing.request_hash != request_hash
                                or existing.credits_authorized != estimated_credits
                            ):
                                raise PermitError("permit_call_reservation_conflict")
                            replay_access = await self._validate_replay_model_access(
                                session=session,
                                model=model,
                                wallet_id=wallet_id,
                                key_id=key_id,
                            )
                            if not replay_access.allowed:
                                return replay_access
                            if existing.state == "released":
                                return PermitValidation(
                                    False,
                                    "permit_call_reservation_released",
                                    model,
                                )
                            if existing.state not in {"reserved", "consumed"}:
                                raise PermitError(
                                    "permit_call_reservation_state_invalid"
                                )
                            return PermitValidation(True, None, model)

                    validation = await self._validate_model_for_action(
                        session=session,
                        model=model,
                        wallet_id=wallet_id,
                        tool_name=tool_name,
                        estimated_credits=estimated_credits,
                        key_id=key_id,
                        arguments=arguments,
                    )
                    if not validation.allowed:
                        return validation
                    # Reserve atomically: a single guarded UPDATE enforces the
                    # cap at the row level, so two concurrent reservations cannot
                    # both pass even on SQLite, where the FOR UPDATE above is a
                    # silent no-op. The read-validated numbers are advisory; this
                    # write is the authority.
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
                                PermitModel.spent_credits + estimated_credits
                                <= PermitModel.max_credits,
                            ),
                            or_(
                                cast(
                                    ColumnElement[bool],
                                    cast(Any, PermitModel.aggregate_value_cap).is_(
                                        None
                                    ),
                                ),
                                cast(
                                    ColumnElement[bool],
                                    PermitModel.spent_credits + estimated_credits
                                    <= cast(Any, PermitModel.aggregate_value_cap),
                                ),
                            ),
                        )
                        .values(
                            spent_credits=PermitModel.spent_credits + estimated_credits,
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if (cast(Any, reserved).rowcount or 0) != 1:
                        # A concurrent reservation consumed the remaining budget
                        # (or a concurrent revocation flipped the status) between
                        # the validation read and this guarded write. Re-read for
                        # an accurate reason and deny — no budget moved.
                        await session.refresh(model)
                        if model.status != "active":
                            return PermitValidation(
                                False,
                                f"permit_{model.status}",
                                model,
                                {
                                    "status": model.status,
                                    "revoked_at": _stamp(model.revoked_at),
                                },
                            )
                        if (
                            model.aggregate_value_cap is not None
                            and model.spent_credits + estimated_credits
                            > model.aggregate_value_cap
                        ):
                            return PermitValidation(
                                False,
                                "permit_aggregate_value_cap_exceeded",
                                model,
                                {
                                    "required_credits": _num(estimated_credits),
                                    "charged_to_date": _num(model.spent_credits),
                                    "reserved_or_charged_to_date": _num(
                                        model.spent_credits
                                    ),
                                    "aggregate_value_cap": _num(
                                        model.aggregate_value_cap
                                    ),
                                },
                            )
                        return PermitValidation(
                            False,
                            "permit_budget_exceeded",
                            model,
                            {
                                "required_credits": _num(estimated_credits),
                                "remaining_credits": _num(
                                    model.max_credits - model.spent_credits
                                ),
                                "spent_credits": _num(model.spent_credits),
                                "max_credits": _num(model.max_credits),
                            },
                        )
                    # Reflect the committed reservation on the returned model.
                    await session.refresh(model)
                    if identity is not None:
                        now = utc_now()
                        session.add(
                            PermitCallReservationModel(
                                idempotency_record_id=identity.record_id,
                                wallet_id=wallet_id,
                                permit_id=permit_id,
                                tool=tool_name,
                                request_hash=identity.request_hash,
                                credits_authorized=estimated_credits,
                                state="reserved",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        # Force unique/FK/check constraints before commit so a
                        # failure rolls the paired budget increment back.
                        await session.flush()
                return validation

        return await self._run_with_write_retry(_once)

    async def consume_local_call(self, idempotency_record_id: str) -> bool:
        """Durably cross the local execution boundary exactly once.

        The commit completes before the callable is entered. A consumed row is
        never released or automatically re-executed after a crash because the
        downstream effect may already have occurred.
        """
        factory = get_session_factory()

        async def _once() -> bool:
            async with factory() as session:
                async with session.begin():
                    now = utc_now()
                    consumed = await session.execute(
                        sa_update(PermitCallReservationModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitCallReservationModel.idempotency_record_id
                                == idempotency_record_id,
                            ),
                            cast(
                                ColumnElement[bool],
                                PermitCallReservationModel.state == "reserved",
                            ),
                            cast(
                                ColumnElement[bool],
                                cast(
                                    Any,
                                    PermitCallReservationModel.execution_started_at,
                                ).is_(None),
                            ),
                        )
                        .values(
                            state="consumed",
                            execution_started_at=now,
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if (cast(Any, consumed).rowcount or 0) == 1:
                        return True
                    reservation = await session.get(
                        PermitCallReservationModel,
                        idempotency_record_id,
                    )
                    if reservation is None:
                        raise PermitError("permit_call_reservation_not_found")
                    if reservation.state == "consumed":
                        return False
                    raise PermitError("permit_call_reservation_state_invalid")

        return await self._run_with_write_retry(_once)

    async def release_local_call_reservation_once(
        self,
        idempotency_record_id: str,
    ) -> bool:
        """Release a proven pre-execution local reservation exactly once.

        Reservation state and permit budget move in one transaction. The lock
        order matches authorization: idempotency, permit, reservation.
        """
        factory = get_session_factory()

        async def _once() -> bool:
            async with factory() as session:
                async with session.begin():
                    identity = await session.get(
                        IdempotencyRecordModel,
                        idempotency_record_id,
                        with_for_update=True,
                    )
                    if identity is None:
                        raise PermitError("permit_call_identity_invalid")
                    permit_id = await session.scalar(
                        select(cast(Any, PermitCallReservationModel.permit_id)).where(
                            cast(
                                ColumnElement[bool],
                                PermitCallReservationModel.idempotency_record_id
                                == idempotency_record_id,
                            )
                        )
                    )
                    if permit_id is None:
                        raise PermitError("permit_call_reservation_not_found")
                    model = await session.get(
                        PermitModel,
                        permit_id,
                        with_for_update=True,
                    )
                    if model is None:
                        raise PermitError("permit_not_found")
                    reservation = await session.scalar(
                        select(PermitCallReservationModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitCallReservationModel.idempotency_record_id
                                == idempotency_record_id,
                            )
                        )
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if reservation is None:
                        raise PermitError("permit_call_reservation_not_found")
                    if reservation.state == "released":
                        return False
                    if (
                        reservation.state != "reserved"
                        or reservation.execution_started_at is not None
                    ):
                        raise PermitError("permit_call_reservation_state_invalid")
                    now = utc_now()
                    await session.execute(
                        sa_update(PermitModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitModel.permit_id == reservation.permit_id,
                            )
                        )
                        .values(
                            spent_credits=case(
                                (
                                    cast(
                                        ColumnElement[bool],
                                        PermitModel.spent_credits
                                        - reservation.credits_authorized
                                        < Decimal("0"),
                                    ),
                                    Decimal("0"),
                                ),
                                else_=PermitModel.spent_credits
                                - reservation.credits_authorized,
                            ),
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    reservation.state = "released"
                    reservation.released_at = now
                    reservation.updated_at = now
                    session.add(reservation)
                return True

        return await self._run_with_write_retry(_once)

    async def _run_with_write_retry(self, operation):
        """Run one full-transaction DB operation, retrying transient SQLite
        write conflicts (WAL "database is locked"/"snapshot" errors a genuinely
        concurrent writer raises). PostgreSQL blocks on the row lock instead of
        raising, so this simply runs ``operation`` once there."""
        last_exc: OperationalError | None = None
        for attempt in range(_PERMIT_WRITE_MAX_ATTEMPTS):
            try:
                return await operation()
            except OperationalError as exc:
                last_exc = exc
                if not _is_retryable_write_conflict(exc):
                    raise
                await asyncio.sleep(min(0.02, 0.002 * (attempt + 1)))
        raise PermitError("permit_write_contended") from last_exc

    async def _validate_model_for_action(
        self,
        *,
        session: AsyncSession | None = None,
        model: PermitModel,
        wallet_id: str,
        tool_name: str,
        estimated_credits: Decimal,
        key_id: str | None,
        arguments: dict[str, Any] | None = None,
    ) -> PermitValidation:
        now = utc_now()
        if model.status != "active":
            return PermitValidation(
                False,
                f"permit_{model.status}",
                model,
                {
                    "status": model.status,
                    "revoked_at": _stamp(model.revoked_at),
                },
            )
        expires_at = to_naive_utc(model.expires_at)
        if expires_at <= now:
            return PermitValidation(
                False,
                "permit_expired",
                model,
                {
                    "expired_at": _stamp(expires_at),
                    "checked_at": _stamp(now),
                },
            )
        # Binding mismatches carry no values: the caller failed to prove it is
        # the subject, so telling it which wallet or key the permit is bound to
        # would answer a question it has not earned.
        if model.subject_wallet_id != wallet_id:
            return PermitValidation(
                False,
                "permit_wallet_mismatch",
                model,
                {"bound_to": "subject_wallet_id"},
            )
        if model.subject_key_id and model.subject_key_id != key_id:
            return PermitValidation(
                False, "permit_key_mismatch", model, {"bound_to": "subject_key_id"}
            )
        allowed_tools = _loads_list(model.allowed_tools_json)
        if allowed_tools and tool_name not in allowed_tools:
            return PermitValidation(
                False,
                "permit_tool_not_allowed",
                model,
                {"requested_tool": tool_name, "allowed_tools": allowed_tools},
            )
        scopes = set(_loads_list(model.scopes_json))
        required_scope = f"tool:{tool_name}:invoke"
        if required_scope not in scopes or "billing:charge" not in scopes:
            required = [required_scope, "billing:charge"]
            return PermitValidation(
                False,
                "permit_scope_missing",
                model,
                {
                    "required_scopes": required,
                    "missing_scopes": [s for s in required if s not in scopes],
                },
            )
        if model.spent_credits + estimated_credits > model.max_credits:
            return PermitValidation(
                False,
                "permit_budget_exceeded",
                model,
                {
                    "required_credits": _num(estimated_credits),
                    "remaining_credits": _num(model.max_credits - model.spent_credits),
                    "spent_credits": _num(model.spent_credits),
                    "max_credits": _num(model.max_credits),
                },
            )

        # Permit schema v2 constraint checks
        # 1. max_calls_per_tool
        max_calls = _loads_dict(model.max_calls_per_tool_json or "{}")
        if max_calls and tool_name in max_calls:
            limit = max_calls[tool_name]
            # Require a genuine JSON integer. `int()` would silently coerce
            # 2.5 -> 2 or "3" -> 3 (and bool is an int subclass), turning a
            # malformed constraint into a permissive one; fail closed instead
            # of raising a 500 on the governed path.
            if type(limit) is not int:
                return PermitValidation(
                    False,
                    "permit_max_calls_exceeded",
                    model,
                    {"tool": tool_name, "limit": "malformed"},
                )
            call_count = await self._count_tool_calls(
                model.permit_id,
                tool_name,
                session=session,
            )
            if call_count >= limit:
                return PermitValidation(
                    False,
                    "permit_max_calls_exceeded",
                    model,
                    {"tool": tool_name, "limit": limit, "calls_made": call_count},
                )

        # 2. aggregate_value_cap
        if model.aggregate_value_cap is not None:
            reserved_or_charged = model.spent_credits
            if reserved_or_charged + estimated_credits > model.aggregate_value_cap:
                return PermitValidation(
                    False,
                    "permit_aggregate_value_cap_exceeded",
                    model,
                    {
                        "required_credits": _num(estimated_credits),
                        "charged_to_date": _num(reserved_or_charged),
                        "reserved_or_charged_to_date": _num(reserved_or_charged),
                        "aggregate_value_cap": _num(model.aggregate_value_cap),
                    },
                )

        # 3. forbidden_fields
        forbidden = _loads_list(model.forbidden_fields_json or "[]")
        if forbidden and arguments:
            hit = _find_forbidden_field(arguments, set(forbidden))
            if hit is not None:
                # The field NAME is echoed, never its value: the value is the
                # thing the permit forbade carrying.
                return PermitValidation(
                    False,
                    f"permit_forbidden_field:{hit}",
                    model,
                    {"field": hit, "forbidden_fields": forbidden},
                )

        if not await self.verify_signature(model, session=session):
            return PermitValidation(
                False,
                "permit_signature_invalid",
                model,
                {"key_id": model.key_id},
            )
        return PermitValidation(True, None, model)

    async def _count_tool_calls(
        self,
        permit_id: str,
        tool_name: str,
        *,
        session: AsyncSession | None = None,
    ) -> int:
        """Count reserved or possibly executed calls for one permit/tool."""

        async def count(current: AsyncSession) -> int:
            attempts = await current.scalar(
                select(func.count())
                .select_from(McpDispatchAttemptModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.permit_id == permit_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        McpDispatchAttemptModel.public_tool_id == tool_name,
                    ),
                    or_(
                        cast(
                            ColumnElement[bool],
                            McpDispatchAttemptModel.state != "returned_error",
                        ),
                        cast(
                            ColumnElement[bool],
                            cast(
                                Any,
                                McpDispatchAttemptModel.dispatched_at,
                            ).is_not(None),
                        ),
                    ),
                )
            )
            local_reservations = await current.scalar(
                select(func.count())
                .select_from(PermitCallReservationModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        PermitCallReservationModel.permit_id == permit_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        PermitCallReservationModel.tool == tool_name,
                    ),
                    cast(
                        ColumnElement[bool],
                        PermitCallReservationModel.state != "released",
                    ),
                )
            )
            unlinked_receipts = await current.scalar(
                select(func.count())
                .select_from(ReceiptModel)
                .outerjoin(
                    PermitCallReservationModel,
                    cast(
                        ColumnElement[bool],
                        PermitCallReservationModel.idempotency_record_id
                        == ReceiptModel.idempotency_record_id,
                    ),
                )
                .where(
                    cast(ColumnElement[bool], ReceiptModel.permit_id == permit_id),
                    cast(ColumnElement[bool], ReceiptModel.tool == tool_name),
                    cast(
                        ColumnElement[bool],
                        cast(Any, ReceiptModel.outcome).in_(
                            [
                                "success",
                                "delivery_uncertain",
                                "response_rejected",
                                "failed_refunded",
                                "failed_unrefunded",
                            ]
                        ),
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, ReceiptModel.dispatch_attempt_id).is_(None),
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(
                            Any,
                            PermitCallReservationModel.idempotency_record_id,
                        ).is_(None),
                    ),
                )
            )
            return (
                int(attempts or 0)
                + int(local_reservations or 0)
                + int(unlinked_receipts or 0)
            )

        if session is not None:
            return await count(session)
        factory = get_session_factory()
        async with factory() as owned_session:
            return await count(owned_session)

    async def reserve_budget(self, permit_id: str, amount: Decimal) -> None:
        factory = get_session_factory()

        async def _once() -> None:
            async with factory() as session:
                async with session.begin():
                    now = utc_now()
                    # Atomic guarded reserve (see authorize_and_reserve): the cap
                    # is enforced by the WHERE clause, not a read-then-write.
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
                                PermitModel.spent_credits + amount
                                <= PermitModel.max_credits,
                            ),
                        )
                        .values(
                            spent_credits=PermitModel.spent_credits + amount,
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if (cast(Any, reserved).rowcount or 0) != 1:
                        exists = await session.get(PermitModel, permit_id)
                        if exists is None:
                            raise PermitError("permit_not_found")
                        raise PermitError("permit_budget_exceeded")

                    # Budget percentage alerts, recomputed from the committed
                    # ``spent_credits`` so a concurrent reservation cannot skew
                    # the threshold arithmetic.
                    model = await session.get(PermitModel, permit_id)
                    if model is not None and model.max_credits > 0:
                        pct = (model.spent_credits / model.max_credits) * 100
                        thresholds = [
                            (Decimal("100"), "critical", "permit_budget_exhausted"),
                            (Decimal("90"), "warning", "permit_budget_90pct"),
                            (Decimal("80"), "info", "permit_budget_80pct"),
                        ]
                        for threshold, severity, alert_type in thresholds:
                            if pct >= threshold:
                                # Only alert on the transition across a threshold.
                                prior_pct = (
                                    (model.spent_credits - amount) / model.max_credits
                                ) * 100
                                if prior_pct < threshold:
                                    session.add(
                                        BillingAlertModel(
                                            alert_id=f"alt-{uuid.uuid4().hex[:12]}",
                                            wallet_id=model.subject_wallet_id,
                                            alert_type=alert_type,
                                            threshold_amount=threshold,
                                            current_balance=model.max_credits
                                            - model.spent_credits,
                                            message=(
                                                f"Permit {permit_id}: {pct:.0f}% of "
                                                f"{model.max_credits} credits spent."
                                            ),
                                            severity=severity,
                                        )
                                    )
                                break  # Only fire the highest crossed threshold

        await self._run_with_write_retry(_once)

    async def release_budget(self, permit_id: str, amount: Decimal) -> None:
        factory = get_session_factory()

        async def _once() -> None:
            async with factory() as session:
                async with session.begin():
                    # Atomic clamped decrement: a single UPDATE so a concurrent
                    # reservation on the same permit cannot be lost to a
                    # read-modify-write refund. A missing permit is a no-op.
                    await session.execute(
                        sa_update(PermitModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitModel.permit_id == permit_id,
                            )
                        )
                        .values(
                            spent_credits=case(
                                (
                                    cast(
                                        ColumnElement[bool],
                                        PermitModel.spent_credits - amount
                                        < Decimal("0"),
                                    ),
                                    Decimal("0"),
                                ),
                                else_=PermitModel.spent_credits - amount,
                            ),
                            updated_at=utc_now(),
                        )
                        .execution_options(synchronize_session=False)
                    )

        await self._run_with_write_retry(_once)

    async def release_dispatch_budget_once(self, attempt_id: str) -> bool:
        """Release one remote attempt's reservation exactly once.

        The permit mutation and attempt checkpoint share one transaction. This
        closes the crash window that exists when a plain ``release_budget``
        call succeeds but the caller dies before recording that it succeeded.
        Returns ``True`` only for the transaction that performed the release.
        """
        factory = get_session_factory()

        async def _once() -> bool:
            async with factory() as session:
                async with session.begin():
                    attempt = await session.get(
                        McpDispatchAttemptModel,
                        attempt_id,
                        with_for_update=True,
                    )
                    if attempt is None:
                        raise PermitError("dispatch_attempt_not_found")
                    if attempt.state != "returned_error":
                        raise PermitError("dispatch_budget_release_state_invalid")
                    if attempt.budget_released_at is not None:
                        return False
                    now = utc_now()
                    # Atomic clamped decrement so a concurrent reservation on the
                    # same permit is not clobbered by a read-modify-write here.
                    released = await session.execute(
                        sa_update(PermitModel)
                        .where(
                            cast(
                                ColumnElement[bool],
                                PermitModel.permit_id == attempt.permit_id,
                            )
                        )
                        .values(
                            spent_credits=case(
                                (
                                    cast(
                                        ColumnElement[bool],
                                        PermitModel.spent_credits
                                        - attempt.credits_authorized
                                        < Decimal("0"),
                                    ),
                                    Decimal("0"),
                                ),
                                else_=PermitModel.spent_credits
                                - attempt.credits_authorized,
                            ),
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if (cast(Any, released).rowcount or 0) == 0:
                        raise PermitError("permit_not_found")
                    attempt.budget_released_at = now
                    attempt.updated_at = now
                    session.add(attempt)
                return True

        return await self._run_with_write_retry(_once)

    async def reconcile_budgets(self, *, idle_seconds: int = 900) -> int:
        """Repair budget reservations orphaned by a crash mid-invocation.

        A governed call reserves budget before charging, so a process death
        between reserve and the receipt write leaves ``spent_credits`` above the
        budget actually consumed. This resets such drift to the sum of the
        permit's successful receipts.

        Crucially, it only ever touches permits that can no longer admit a new
        charge -- non-active (revoked) OR already past ``expires_at``. A live,
        chargeable permit is never downward-reset here, because a governed call
        that outlives ``idle_seconds`` looks identical to a crashed one from the
        outside (no mid-call heartbeat), and resetting a still-live reservation
        would let a concurrent request over-spend past ``max_credits``.
        ``validate_for_action`` rejects both non-active and expired permits, so
        reclaiming their budget can never enable an over-spend. A crashed
        reservation on a still-active permit is left conservatively in place
        (the agent can spend *less* than authorized, never more) and is
        reclaimed once the permit expires. Returns the number corrected.
        """
        from app.db.models import (
            IdempotencyRecordModel,
            LedgerEntryModel,
            ReceiptModel,
        )

        # Persisted datetimes in this codebase are naive UTC (see
        # app.core.time.utc_now); the reconcile columns (expires_at,
        # updated_at, issued_at) are naive DateTime. Build the comparison
        # bounds naive too, so the SQL comparison isn't skewed by a tz-aware
        # parameter being cast against the session timezone on Postgres.
        now = utc_now()
        cutoff = now - timedelta(seconds=idle_seconds)
        factory = get_session_factory()
        corrected = 0
        async with factory() as session:
            async with session.begin():
                stale = (
                    (
                        await session.execute(
                            select(PermitModel)
                            .where(
                                or_(
                                    cast(
                                        ColumnElement[bool],
                                        PermitModel.status != "active",
                                    ),
                                    cast(
                                        ColumnElement[bool],
                                        PermitModel.expires_at <= now,
                                    ),
                                ),
                                cast(
                                    ColumnElement[bool],
                                    func.coalesce(
                                        PermitModel.updated_at, PermitModel.issued_at
                                    )
                                    < cutoff,
                                ),
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                for permit in stale:
                    receipt_rows = (
                        await session.execute(
                            select(
                                cast(Any, ReceiptModel.receipt_id),
                                cast(Any, ReceiptModel.outcome),
                                cast(Any, ReceiptModel.credits_charged),
                                cast(Any, ReceiptModel.ledger_entry_id),
                                cast(Any, ReceiptModel.wallet_id),
                            ).where(
                                cast(
                                    ColumnElement[bool],
                                    ReceiptModel.permit_id == permit.permit_id,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    cast(Any, ReceiptModel.outcome).in_(
                                        [
                                            "success",
                                            "delivery_uncertain",
                                            "response_rejected",
                                            "failed_unrefunded",
                                        ]
                                    ),
                                ),
                            )
                        )
                    ).all()
                    pending_ledger_ids = [
                        ledger_entry_id
                        for (
                            _receipt_id,
                            outcome,
                            _credits,
                            ledger_entry_id,
                            _wallet_id,
                        ) in receipt_rows
                        if outcome == "failed_unrefunded"
                        and ledger_entry_id is not None
                    ]
                    exact_refunded_ledger_ids: set[str] = set()
                    if pending_ledger_ids:
                        refund_rows = (
                            await session.execute(
                                select(
                                    cast(Any, LedgerEntryModel.entry_id),
                                    cast(Any, LedgerEntryModel.wallet_id),
                                    cast(Any, LedgerEntryModel.amount),
                                    cast(Any, LedgerEntryModel.correlation_id),
                                ).where(
                                    cast(
                                        ColumnElement[bool],
                                        LedgerEntryModel.action == "refund",
                                    ),
                                    cast(
                                        ColumnElement[bool],
                                        cast(
                                            Any,
                                            LedgerEntryModel.correlation_id,
                                        ).in_(pending_ledger_ids),
                                    ),
                                )
                            )
                        ).all()
                        failed_by_ledger = {
                            ledger_entry_id: (wallet_id, Decimal(str(credits)))
                            for (
                                _receipt_id,
                                outcome,
                                credits,
                                ledger_entry_id,
                                wallet_id,
                            ) in receipt_rows
                            if outcome == "failed_unrefunded"
                            and ledger_entry_id is not None
                        }
                        exact_refunded_ledger_ids = {
                            correlation_id
                            for entry_id, wallet_id, amount, correlation_id in refund_rows
                            if correlation_id in failed_by_ledger
                            and entry_id == f"refund-{correlation_id}"
                            and wallet_id == failed_by_ledger[correlation_id][0]
                            and Decimal(str(amount))
                            == failed_by_ledger[correlation_id][1]
                        }
                    failed_receipt_by_id = {
                        receipt_id: ledger_entry_id
                        for (
                            receipt_id,
                            outcome,
                            _credits,
                            ledger_entry_id,
                            _wallet_id,
                        ) in receipt_rows
                        if outcome == "failed_unrefunded"
                        and ledger_entry_id in exact_refunded_ledger_ids
                    }
                    resolved_receipt_ids: set[str] = set()
                    if failed_receipt_by_id:
                        state_rows = (
                            await session.execute(
                                select(
                                    cast(
                                        Any,
                                        IdempotencyRecordModel.response_reference,
                                    ),
                                    cast(Any, IdempotencyRecordModel.response_json),
                                ).where(
                                    cast(
                                        ColumnElement[bool],
                                        cast(
                                            Any,
                                            IdempotencyRecordModel.response_reference,
                                        ).in_(list(failed_receipt_by_id)),
                                    )
                                )
                            )
                        ).all()
                        for receipt_id, response_json in state_rows:
                            try:
                                response = json.loads(response_json or "")
                            except (json.JSONDecodeError, TypeError):
                                continue
                            state = (
                                response.get("refund_reconciliation")
                                if isinstance(response, dict)
                                else None
                            )
                            if (
                                isinstance(state, dict)
                                and state.get("status") == "resolved"
                                and state.get("receipt_id") == receipt_id
                                and state.get("ledger_entry_id")
                                == failed_receipt_by_id[receipt_id]
                            ):
                                resolved_receipt_ids.add(receipt_id)
                    consumed_decimal = sum(
                        (
                            Decimal(str(credits))
                            for (
                                receipt_id,
                                outcome,
                                credits,
                                _ledger_entry_id,
                                _wallet_id,
                            ) in receipt_rows
                            if outcome
                            in {"success", "delivery_uncertain", "response_rejected"}
                            or (
                                outcome == "failed_unrefunded"
                                and receipt_id not in resolved_receipt_ids
                            )
                        ),
                        Decimal("0"),
                    )
                    if permit.spent_credits != consumed_decimal:
                        permit.spent_credits = consumed_decimal
                        permit.updated_at = utc_now()
                        session.add(permit)
                        corrected += 1
            await session.commit()
        return corrected

    async def verify_signature(
        self, model: PermitModel, *, session: AsyncSession | None = None
    ) -> bool:
        payload: dict[str, Any] = {
            "permit_id": model.permit_id,
            "issuer_wallet_id": model.issuer_wallet_id,
            "subject_wallet_id": model.subject_wallet_id,
            "subject_key_id": model.subject_key_id,
            "scopes": _loads_list(model.scopes_json),
            "allowed_tools": _loads_list(model.allowed_tools_json),
            "max_credits": model.max_credits,
            "expires_at": model.expires_at,
            "nonce": model.nonce,
            "status": "active",
            "issued_at": model.issued_at,
            "alg": "Ed25519",
            "kid": model.key_id,
        }
        # Mirror of create_permit: the key is present in the signed payload
        # only when true. Flipping the stored flag in either direction breaks
        # the rebuilt payload and fails verification.
        if model.requires_human_approval:
            payload["requires_human_approval"] = True
        # Permit schema v2 constraints — mirrored from create_permit
        max_calls = _loads_dict(model.max_calls_per_tool_json or "{}")
        if max_calls:
            payload["max_calls_per_tool"] = max_calls
        if model.aggregate_value_cap is not None:
            payload["aggregate_value_cap"] = model.aggregate_value_cap
        forbidden = _loads_list(model.forbidden_fields_json or "[]")
        if forbidden:
            payload["forbidden_fields"] = forbidden
        if model.recipient_domain:
            payload["recipient_domain"] = model.recipient_domain
        from app.services.signing_keys import sha256_hex

        payload["payload_hash"] = sha256_hex(payload)
        return await get_signing_key_service().verify_payload(
            payload,
            signature=model.signature,
            key_id=model.key_id,
            session=session,
        )


_service: PermitService | None = None


def get_permit_service() -> PermitService:
    global _service
    if _service is None:
        _service = PermitService()
    return _service
