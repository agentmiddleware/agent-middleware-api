from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class PermitCreateRequest(BaseModel):
    issuer_wallet_id: str
    subject_wallet_id: str
    subject_key_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    max_credits: Decimal
    expires_at: datetime
    nonce: str | None = None


class PermitResponse(BaseModel):
    permit_id: str
    issuer_wallet_id: str
    subject_wallet_id: str
    subject_key_id: str | None
    scopes: list[str]
    allowed_tools: list[str]
    max_credits: Decimal
    spent_credits: Decimal
    expires_at: datetime
    nonce: str
    status: str
    signature: str
    key_id: str
    issued_at: datetime


class PermitVerifyRequest(BaseModel):
    permit_id: str
    wallet_id: str | None = None
    tool: str | None = None
    estimated_credits: Decimal | None = None


class PermitVerifyResponse(BaseModel):
    valid: bool
    reason: str | None = None
    permit: PermitResponse | None = None


class ReceiptResponse(BaseModel):
    receipt_id: str
    permit_id: str
    wallet_id: str
    key_id: str | None
    tool: str
    request_hash: str
    response_hash: str | None
    ledger_entry_id: str | None
    credits_authorized: Decimal
    credits_charged: Decimal
    outcome: str
    audit_event_id: str | None
    created_at: datetime
    signature: str
    signature_key_id: str


class ReceiptVerifyRequest(BaseModel):
    receipt_id: str


class ReceiptVerifyResponse(BaseModel):
    valid: bool
    reason: str | None = None
    receipt: ReceiptResponse | None = None


class AuditChainVerifyRequest(BaseModel):
    wallet_id: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class AuditChainVerifyResponse(BaseModel):
    valid: bool
    checked_events: int
    first_event_id: str | None = None
    last_event_id: str | None = None
    reason: str | None = None
    broken_event_id: str | None = None


class TrustMcpMetadata(BaseModel):
    permit_id: str | None = None
    receipt_id: str | None = None
    idempotency_key: str | None = None
    request_hash: str | None = None
    receipt: dict[str, Any] | None = None
