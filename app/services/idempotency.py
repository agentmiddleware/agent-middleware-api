from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel
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
                    IdempotencyRecordModel.wallet_id == wallet_id,
                    IdempotencyRecordModel.endpoint == endpoint,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
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

            session.add(
                IdempotencyRecordModel(
                    record_id=f"idm-{uuid.uuid4().hex[:16]}",
                    wallet_id=wallet_id,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
            )
            await session.commit()
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
                    IdempotencyRecordModel.wallet_id == wallet_id,
                    IdempotencyRecordModel.endpoint == endpoint,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
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


_service: IdempotencyService | None = None


def get_idempotency_service() -> IdempotencyService:
    global _service
    if _service is None:
        _service = IdempotencyService()
    return _service
