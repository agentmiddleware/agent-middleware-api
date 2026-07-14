from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import PermitModel, WalletModel
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
        signature=model.signature,
        key_id=model.key_id,
        issued_at=model.issued_at,
        revoked_at=model.revoked_at,
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
            filters.append(
                cast(ColumnElement[bool], PermitModel.issued_at >= created_after)
            )
        if created_before:
            filters.append(
                cast(ColumnElement[bool], PermitModel.issued_at <= created_before)
            )
        if expires_after:
            filters.append(
                cast(ColumnElement[bool], PermitModel.expires_at >= expires_after)
            )
        if expires_before:
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

    async def create_permit(self, request: PermitCreateRequest) -> PermitResponse:
        if request.max_credits <= Decimal("0"):
            raise PermitError("max_credits_must_be_positive")
        expires_at = request.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise PermitError("permit_expired_at_creation")
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

        now = datetime.now(timezone.utc)
        permit_id = f"permit-{uuid.uuid4().hex[:16]}"
        nonce = request.nonce or uuid.uuid4().hex
        payload = {
            "permit_id": permit_id,
            "issuer_wallet_id": request.issuer_wallet_id,
            "subject_wallet_id": request.subject_wallet_id,
            "subject_key_id": request.subject_key_id,
            "scopes": scopes,
            "allowed_tools": request.allowed_tools,
            "max_credits": request.max_credits,
            "expires_at": expires_at,
            "nonce": nonce,
            "status": "active",
            "issued_at": now,
        }
        signature, key_id, _ = await get_signing_key_service().sign_payload(payload)

        model = PermitModel(
            permit_id=permit_id,
            issuer_wallet_id=request.issuer_wallet_id,
            subject_wallet_id=request.subject_wallet_id,
            subject_key_id=request.subject_key_id,
            scopes_json=json.dumps(scopes),
            allowed_tools_json=json.dumps(request.allowed_tools),
            max_credits=request.max_credits,
            expires_at=expires_at,
            nonce=nonce,
            status="active",
            signature=signature,
            key_id=key_id,
            issued_at=now,
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
            model.revoked_at = datetime.now(timezone.utc)
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
    ) -> PermitValidation:
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            if not model:
                return PermitValidation(False, "permit_not_found", None)
            if model.status != "active":
                return PermitValidation(False, f"permit_{model.status}", model)
            expires_at = model.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
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
            if not await self.verify_signature(model):
                return PermitValidation(False, "permit_signature_invalid", model)
            return PermitValidation(True, None, model)

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
                model.updated_at = datetime.now(timezone.utc)
                session.add(model)
            await session.commit()

    async def release_budget(self, permit_id: str, amount: Decimal) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                model = await session.get(PermitModel, permit_id, with_for_update=True)
                if not model:
                    return
                model.spent_credits = max(Decimal("0"), model.spent_credits - amount)
                model.updated_at = datetime.now(timezone.utc)
                session.add(model)
            await session.commit()

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
        from app.db.models import ReceiptModel

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
                ).scalars().all()
                for permit in stale:
                    consumed = (
                        await session.execute(
                            select(
                                func.coalesce(
                                    func.sum(ReceiptModel.credits_charged),
                                    0,
                                )
                            ).where(
                                cast(
                                    ColumnElement[bool],
                                    ReceiptModel.permit_id == permit.permit_id,
                                ),
                                cast(
                                    ColumnElement[bool],
                                    ReceiptModel.outcome == "success",
                                ),
                            )
                        )
                    ).scalar_one()
                    consumed_decimal = Decimal(str(consumed))
                    if permit.spent_credits != consumed_decimal:
                        permit.spent_credits = consumed_decimal
                        permit.updated_at = utc_now()
                        session.add(permit)
                        corrected += 1
            await session.commit()
        return corrected

    async def verify_signature(self, model: PermitModel) -> bool:
        payload = {
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
