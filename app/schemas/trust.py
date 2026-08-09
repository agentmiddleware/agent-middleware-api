from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

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
    # Governed invokes under this permit block on a human decision (Sentinel)
    # before budget is reserved or credits are charged.
    requires_human_approval: bool = False
    # Permit schema v2 constraints (all optional)
    max_calls_per_tool: dict[str, int] = Field(default_factory=dict)
    aggregate_value_cap: Decimal | None = None
    forbidden_fields: list[str] = Field(default_factory=list)
    recipient_domain: str | None = None


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
    requires_human_approval: bool = False
    signature: str
    key_id: str
    issued_at: datetime
    revoked_at: datetime | None = None
    # Permit schema v2 constraints
    max_calls_per_tool: dict[str, int] = Field(default_factory=dict)
    aggregate_value_cap: Decimal | None = None
    forbidden_fields: list[str] = Field(default_factory=list)
    recipient_domain: str | None = None


class PermitListResponse(BaseModel):
    permits: list[PermitResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


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
    idempotency_record_id: str | None = None
    dispatch_attempt_id: str | None = None
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
    # Human approval that authorized this invoke, when the permit required one.
    approval_id: str | None = None
    # Permit schema v2: snapshot of constraints evaluated at invoke time
    constraints_evaluated: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    signature: str
    signature_key_id: str


class ReceiptListResponse(BaseModel):
    receipts: list[ReceiptResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


class RefundReconciliationItem(BaseModel):
    record_id: str
    receipt_id: str
    wallet_id: str
    permit_id: str
    ledger_entry_id: str
    refund_entry_id: str
    credits: Decimal
    status: Literal["pending", "resolved"]
    created_at: datetime
    resolved_at: datetime | None = None


class RefundReconciliationListResponse(BaseModel):
    items: list[RefundReconciliationItem]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


class RefundReconciliationRetryResponse(BaseModel):
    item: RefundReconciliationItem
    replayed: bool


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


class ReceiptEvidenceCheck(BaseModel):
    name: str
    status: Literal["passed", "failed", "skipped"]
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DispatchEvidenceResponse(BaseModel):
    """Sanitized upstream-dispatch evidence; result payloads and secrets stay private."""

    attempt_id: str
    state: str
    public_tool_id: str
    upstream_tool_name: str
    upstream_origin: str
    request_hash: str
    response_hash: str | None = None
    ledger_entry_id: str | None = None
    credits_authorized: Decimal
    credits_charged: Decimal
    error_code: str | None = None
    created_at: datetime
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None


class ReceiptEvidenceResponse(BaseModel):
    receipt_id: str
    valid: bool
    checks: list[ReceiptEvidenceCheck]
    receipt: ReceiptResponse
    permit: PermitResponse | None = None
    audit_event: dict[str, Any] | None = None
    audit_chain: AuditChainVerifyResponse | None = None
    ledger_entry: dict[str, Any] | None = None
    dispatch: DispatchEvidenceResponse | None = None


class EvidenceBundleResponse(BaseModel):
    """Flat, buyer-facing trust artifact for a single receipt."""

    receipt_id: str
    valid: bool
    receipt: ReceiptResponse
    permit: PermitResponse | None = None
    ledger_entry: dict[str, Any] | None = None
    audit_event: dict[str, Any] | None = None
    dispatch: DispatchEvidenceResponse | None = None
    verification: dict[str, str] = Field(default_factory=dict)


class TrustMcpMetadata(BaseModel):
    permit_id: str | None = None
    receipt_id: str | None = None
    idempotency_key: str | None = None
    request_hash: str | None = None
    receipt: dict[str, Any] | None = None


class SigningKeyMetadataResponse(BaseModel):
    key_id: str
    alg: str
    public_key_b64: str
    status: str
    created_at: datetime
    activated_at: datetime | None = None
    retired_at: datetime | None = None


SigningKeyResponse = SigningKeyMetadataResponse
