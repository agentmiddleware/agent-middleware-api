from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
import uuid

from sqlalchemy import desc, select

from app.db.database import get_session_factory
from app.db.models import ControlPlaneAuditEventModel


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    created_at: datetime
    event: str
    wallet_id: str | None
    tool: str | None
    endpoint: str | None
    auth_source: str | None
    key_id: str | None
    policy_decision_id: str | None
    request_id: str | None
    ok: bool
    error: str | None
    metadata: dict[str, Any]


def _to_event(row: ControlPlaneAuditEventModel) -> AuditEvent:
    metadata: dict[str, Any] = {}
    if row.metadata_json:
        metadata = json.loads(row.metadata_json)
    return AuditEvent(
        event_id=row.event_id,
        created_at=row.created_at,
        event=row.event,
        wallet_id=row.wallet_id,
        tool=row.tool,
        endpoint=row.endpoint,
        auth_source=row.auth_source,
        key_id=row.key_id,
        policy_decision_id=row.policy_decision_id,
        request_id=row.request_id,
        ok=row.ok,
        error=row.error,
        metadata=metadata,
    )


async def record_audit_event(
    *,
    event: str,
    wallet_id: str | None = None,
    tool: str | None = None,
    endpoint: str | None = None,
    auth_source: str | None = None,
    key_id: str | None = None,
    policy_decision_id: str | None = None,
    request_id: str | None = None,
    ok: bool = True,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    model = ControlPlaneAuditEventModel(
        event_id=f"audit-{uuid.uuid4().hex[:16]}",
        event=event,
        wallet_id=wallet_id,
        tool=tool,
        endpoint=endpoint,
        auth_source=auth_source,
        key_id=key_id,
        policy_decision_id=policy_decision_id,
        request_id=request_id,
        ok=ok,
        error=error,
        metadata_json=json.dumps(metadata or {}, default=str),
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(model)
        await session.commit()
        await session.refresh(model)
    return _to_event(model)


async def list_audit_events(
    *,
    wallet_id: str | None = None,
    key_id: str | None = None,
    tool: str | None = None,
    request_id: str | None = None,
    limit: int = 50,
) -> list[AuditEvent]:
    stmt = select(ControlPlaneAuditEventModel).order_by(
        desc(ControlPlaneAuditEventModel.created_at)
    ).limit(limit)
    if wallet_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.wallet_id == wallet_id)
    if key_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.key_id == key_id)
    if tool:
        stmt = stmt.where(ControlPlaneAuditEventModel.tool == tool)
    if request_id:
        stmt = stmt.where(ControlPlaneAuditEventModel.request_id == request_id)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(stmt)
        return [_to_event(row) for row in result.scalars().all()]
