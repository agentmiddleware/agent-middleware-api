from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    BillingAlertModel,
    McpDispatchAttemptModel,
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
    allowed: bool
    reason: str | None
    permit: PermitModel | None


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
        self, request: PermitCreateRequest, subject_key_id: str | None = None
    ) -> PermitResponse:
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

        permit_id = f"permit-{uuid.uuid4().hex[:16]}"
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
            max_calls_per_tool_json=json.dumps(request.max_calls_per_tool) if request.max_calls_per_tool else None,
            aggregate_value_cap=request.aggregate_value_cap,
            forbidden_fields_json=json.dumps(request.forbidden_fields) if request.forbidden_fields else None,
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
            if model.subject_wallet_id != wallet_id:
                return PermitValidation(False, "permit_wallet_mismatch", model)
            if model.subject_key_id and model.subject_key_id != key_id:
                return PermitValidation(False, "permit_key_mismatch", model)
            if not await self.verify_signature(model):
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
    ) -> PermitValidation:
        """Atomically authorize an action and reserve its permit budget.

        The permit row remains locked from the final authorization checks
        through the ``spent_credits`` update. A revocation, expiry, scope
        change, key mismatch, signature failure, or concurrent reservation
        therefore cannot slip between a stale read and the budget mutation.
        """
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                model = await session.get(PermitModel, permit_id, with_for_update=True)
                if not model:
                    return PermitValidation(False, "permit_not_found", None)
                validation = await self._validate_model_for_action(
                    model=model,
                    wallet_id=wallet_id,
                    tool_name=tool_name,
                    estimated_credits=estimated_credits,
                    key_id=key_id,
                    arguments=arguments,
                )
                if not validation.allowed:
                    return validation
                model.spent_credits += estimated_credits
                model.updated_at = utc_now()
                session.add(model)
            return validation

    async def _validate_model_for_action(
        self,
        *,
        model: PermitModel,
        wallet_id: str,
        tool_name: str,
        estimated_credits: Decimal,
        key_id: str | None,
        arguments: dict[str, Any] | None = None,
    ) -> PermitValidation:
        if model.status != "active":
            return PermitValidation(False, f"permit_{model.status}", model)
        expires_at = to_naive_utc(model.expires_at)
        if expires_at <= utc_now():
            return PermitValidation(False, "permit_expired", model)
        if model.subject_wallet_id != wallet_id:
            return PermitValidation(False, "permit_wallet_mismatch", model)
        if model.subject_key_id and model.subject_key_id != key_id:
            return PermitValidation(False, "permit_key_mismatch", model)
        allowed_tools = _loads_list(model.allowed_tools_json)
        if allowed_tools and tool_name not in allowed_tools:
            return PermitValidation(False, "permit_tool_not_allowed", model)
        scopes = set(_loads_list(model.scopes_json))
        required_scope = f"tool:{tool_name}:invoke"
        if required_scope not in scopes or "billing:charge" not in scopes:
            return PermitValidation(False, "permit_scope_missing", model)
        if model.spent_credits + estimated_credits > model.max_credits:
            return PermitValidation(False, "permit_budget_exceeded", model)

        # Permit schema v2 constraint checks
        # 1. max_calls_per_tool
        max_calls = _loads_dict(model.max_calls_per_tool_json or "{}")
        if max_calls and tool_name in max_calls:
            try:
                limit = int(max_calls[tool_name])
            except (TypeError, ValueError):
                # An uninterpretable limit is a malformed constraint; fail
                # closed rather than raising a 500 on the governed path.
                return PermitValidation(False, "permit_max_calls_exceeded", model)
            call_count = await self._count_tool_calls(model.permit_id, tool_name)
            if call_count >= limit:
                return PermitValidation(False, "permit_max_calls_exceeded", model)

        # 2. aggregate_value_cap
        if model.aggregate_value_cap is not None:
            total_charged = await self._sum_permit_charges(model.permit_id)
            if total_charged + estimated_credits > model.aggregate_value_cap:
                return PermitValidation(False, "permit_aggregate_value_cap_exceeded", model)

        # 3. forbidden_fields
        forbidden = _loads_list(model.forbidden_fields_json or "[]")
        if forbidden and arguments:
            hit = _find_forbidden_field(arguments, set(forbidden))
            if hit is not None:
                return PermitValidation(False, f"permit_forbidden_field:{hit}", model)

        if not await self.verify_signature(model):
            return PermitValidation(False, "permit_signature_invalid", model)
        return PermitValidation(True, None, model)

    async def _count_tool_calls(self, permit_id: str, tool_name: str) -> int:
        """Count successful receipts for (permit_id, tool_name)."""
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(func.count()).select_from(ReceiptModel).where(
                    cast(ColumnElement[bool], ReceiptModel.permit_id == permit_id),
                    cast(ColumnElement[bool], ReceiptModel.tool == tool_name),
                    cast(ColumnElement[bool], ReceiptModel.outcome == "success"),
                )
            )
            return int(result.scalar() or 0)

    async def _sum_permit_charges(self, permit_id: str) -> Decimal:
        """Sum credits_charged across all receipts for this permit."""
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(func.sum(ReceiptModel.credits_charged)).where(
                    cast(ColumnElement[bool], ReceiptModel.permit_id == permit_id),
                )
            )
            total = result.scalar()
            return Decimal(str(total)) if total is not None else Decimal("0")

    async def reserve_budget(self, permit_id: str, amount: Decimal) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                model = await session.get(PermitModel, permit_id, with_for_update=True)
                if not model:
                    raise PermitError("permit_not_found")
                if model.spent_credits + amount > model.max_credits:
                    raise PermitError("permit_budget_exceeded")
                model.spent_credits += amount
                model.updated_at = utc_now()
                session.add(model)

                # Budget percentage alerts
                if model.max_credits > 0:
                    pct = (model.spent_credits / model.max_credits) * 100
                    thresholds = [
                        (Decimal("100"), "critical", "permit_budget_exhausted"),
                        (Decimal("90"), "warning", "permit_budget_90pct"),
                        (Decimal("80"), "info", "permit_budget_80pct"),
                    ]
                    for threshold, severity, alert_type in thresholds:
                        if pct >= threshold:
                            # Only create alert if we just crossed this threshold
                            prior_pct = (
                                (model.spent_credits - amount) / model.max_credits
                            ) * 100
                            if prior_pct < threshold:
                                alert = BillingAlertModel(
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
                                session.add(alert)
                            break  # Only fire the highest crossed threshold
            await session.commit()

    async def release_budget(self, permit_id: str, amount: Decimal) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                model = await session.get(PermitModel, permit_id, with_for_update=True)
                if not model:
                    return
                model.spent_credits = max(Decimal("0"), model.spent_credits - amount)
                model.updated_at = utc_now()
                session.add(model)
            await session.commit()

    async def release_dispatch_budget_once(self, attempt_id: str) -> bool:
        """Release one remote attempt's reservation exactly once.

        The permit mutation and attempt checkpoint share one transaction. This
        closes the crash window that exists when a plain ``release_budget``
        call succeeds but the caller dies before recording that it succeeded.
        Returns ``True`` only for the transaction that performed the release.
        """
        factory = get_session_factory()
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
                model = await session.get(
                    PermitModel,
                    attempt.permit_id,
                    with_for_update=True,
                )
                if model is None:
                    raise PermitError("permit_not_found")
                model.spent_credits = max(
                    Decimal("0"),
                    model.spent_credits - attempt.credits_authorized,
                )
                now = utc_now()
                model.updated_at = now
                attempt.budget_released_at = now
                attempt.updated_at = now
                session.add(model)
                session.add(attempt)
            return True

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

    async def verify_signature(self, model: PermitModel) -> bool:
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
        )


_service: PermitService | None = None


def get_permit_service() -> PermitService:
    global _service
    if _service is None:
        _service = PermitService()
    return _service
