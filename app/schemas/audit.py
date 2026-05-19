from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
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


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    total: int
