from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.database import get_session_factory
from app.db.models import ReceiptModel
from app.schemas.trust import ReceiptResponse
from app.services.signing_keys import get_signing_key_service, sha256_hex


class ReceiptError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def receipt_model_to_response(model: ReceiptModel) -> ReceiptResponse:
    return ReceiptResponse(
        receipt_id=model.receipt_id,
        permit_id=model.permit_id,
        wallet_id=model.wallet_id,
        key_id=model.key_id,
        tool=model.tool,
        request_hash=model.request_hash,
        response_hash=model.response_hash,
        ledger_entry_id=model.ledger_entry_id,
        credits_authorized=model.credits_authorized,
        credits_charged=model.credits_charged,
        outcome=model.outcome,
        audit_event_id=model.audit_event_id,
        created_at=model.created_at,
        signature=model.signature,
        signature_key_id=model.signature_key_id,
    )


class ReceiptService:
    async def create_receipt(
        self,
        *,
        permit_id: str,
        wallet_id: str,
        key_id: str | None,
        tool: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        ledger_entry_id: str | None,
        credits_authorized: Decimal,
        credits_charged: Decimal,
        outcome: str,
        audit_event_id: str | None,
    ) -> ReceiptResponse:
        created_at = datetime.now(timezone.utc)
        request_hash = sha256_hex(request_payload)
        response_hash = (
            sha256_hex(response_payload) if response_payload is not None else None
        )
        receipt_id = f"rcpt-{uuid.uuid4().hex[:16]}"
        payload = {
            "receipt_id": receipt_id,
            "permit_id": permit_id,
            "wallet_id": wallet_id,
            "key_id": key_id,
            "tool": tool,
            "request_hash": request_hash,
            "response_hash": response_hash,
            "ledger_entry_id": ledger_entry_id,
            "credits_authorized": credits_authorized,
            "credits_charged": credits_charged,
            "outcome": outcome,
            "audit_event_id": audit_event_id,
            "created_at": created_at,
        }
        signature, signature_key_id, _ = await get_signing_key_service().sign_payload(
            payload
        )
        model = ReceiptModel(
            receipt_id=receipt_id,
            permit_id=permit_id,
            wallet_id=wallet_id,
            key_id=key_id,
            tool=tool,
            request_hash=request_hash,
            response_hash=response_hash,
            ledger_entry_id=ledger_entry_id,
            credits_authorized=credits_authorized,
            credits_charged=credits_charged,
            outcome=outcome,
            audit_event_id=audit_event_id,
            created_at=created_at,
            signature=signature,
            signature_key_id=signature_key_id,
        )
        factory = get_session_factory()
        async with factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return receipt_model_to_response(model)

    async def get_receipt(self, receipt_id: str) -> ReceiptResponse | None:
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(ReceiptModel, receipt_id)
            return receipt_model_to_response(model) if model else None

    async def list_receipts(
        self,
        *,
        permit_id: str | None = None,
        wallet_id: str | None = None,
        tool: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReceiptResponse], int]:
        stmt = select(ReceiptModel)
        count_stmt = select(func.count()).select_from(ReceiptModel)

        filters: list[ColumnElement[bool]] = []
        if permit_id:
            filters.append(cast(ColumnElement[bool], ReceiptModel.permit_id == permit_id))
        if wallet_id:
            filters.append(cast(ColumnElement[bool], ReceiptModel.wallet_id == wallet_id))
        if tool:
            filters.append(cast(ColumnElement[bool], ReceiptModel.tool == tool))
        if outcome:
            filters.append(cast(ColumnElement[bool], ReceiptModel.outcome == outcome))

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        stmt = (
            stmt.order_by(cast(ColumnElement[Any], ReceiptModel.created_at).desc())
            .limit(limit)
            .offset(offset)
        )

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(stmt)
            total = await session.scalar(count_stmt)
            receipts = [
                receipt_model_to_response(model) for model in result.scalars()
            ]
            return receipts, int(total or 0)

    async def verify_receipt(
        self,
        receipt_id: str,
    ) -> tuple[bool, str | None, ReceiptResponse | None]:
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(ReceiptModel, receipt_id)
            if not model:
                return False, "receipt_not_found", None
            payload = {
                "receipt_id": model.receipt_id,
                "permit_id": model.permit_id,
                "wallet_id": model.wallet_id,
                "key_id": model.key_id,
                "tool": model.tool,
                "request_hash": model.request_hash,
                "response_hash": model.response_hash,
                "ledger_entry_id": model.ledger_entry_id,
                "credits_authorized": model.credits_authorized,
                "credits_charged": model.credits_charged,
                "outcome": model.outcome,
                "audit_event_id": model.audit_event_id,
                "created_at": model.created_at,
                "alg": "Ed25519",
                "kid": model.signature_key_id,
            }
            payload["payload_hash"] = sha256_hex(payload)
            ok = await get_signing_key_service().verify_payload(
                payload,
                signature=model.signature,
                key_id=model.signature_key_id,
            )
            return (
                ok,
                None if ok else "receipt_signature_invalid",
                receipt_model_to_response(model),
            )


_service: ReceiptService | None = None


def get_receipt_service() -> ReceiptService:
    global _service
    if _service is None:
        _service = ReceiptService()
    return _service
