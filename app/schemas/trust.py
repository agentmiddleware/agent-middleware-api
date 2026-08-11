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


class QuoteCreateRequest(BaseModel):
    """Ask what one call of a tool will cost this wallet."""

    wallet_id: str
    tool: str


class QuoteResponse(BaseModel):
    quote_id: str
    wallet_id: str
    tool: str
    # What the invoke will charge if this quote is presented before it expires.
    quoted_credits: Decimal
    category: str
    status: Literal["active", "consumed", "expired"]
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    signature: str
    key_id: str


class QuoteListResponse(BaseModel):
    quotes: list[QuoteResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


class PermitRequestCreate(BaseModel):
    """An agent asking a human for authority it cannot mint itself."""

    issuer_wallet_id: str
    subject_wallet_id: str
    allowed_tools: list[str] = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    max_credits: Decimal = Field(gt=0)
    expires_at: datetime
    # Shown to the human approver: why the agent needs this authority.
    justification: str = Field(min_length=1, max_length=2000)
    # Carried onto the minted permit: invokes under it pause for a human too.
    requires_human_approval: bool = False


class PermitRequestResponse(BaseModel):
    request_id: str
    status: Literal[
        "pending", "minting", "approved", "rejected", "expired", "failed"
    ]
    issuer_wallet_id: str
    subject_wallet_id: str
    subject_key_id: str | None = None
    allowed_tools: list[str]
    scopes: list[str]
    max_credits: Decimal
    permit_expires_at: datetime
    requires_human_approval: bool
    justification: str
    requested_at: datetime
    # Local decision deadline. A decision arriving after it is not honored.
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    reason: str | None = None
    simulated: bool = False
    # Set once the permit exists; the whole point of polling.
    permit_id: str | None = None
    permit: PermitResponse | None = None
    # Where the agent polls for the decision.
    poll_url: str


class PermitRequestListResponse(BaseModel):
    requests: list[PermitRequestResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None


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


class PortableReceiptResponse(BaseModel):
    """A receipt as self-contained, offline-verifiable evidence.

    Everything needed to check the signature travels in this object, except
    the public key — which is published unauthenticated at ``keys_url``. A
    holder verifies it without an account, a credential, or any call back to
    the plane that issued it.
    """

    schema_version: str = "1.0"
    receipt_id: str
    issuer: str = Field(
        description="Public origin of the issuing plane; empty when PUBLIC_URL is unset."
    )
    alg: str = "Ed25519"
    kid: str = Field(description="Identifies which published key signed this receipt.")
    canonicalization: str = Field(
        description="Canonical-JSON contract version the signing_input follows."
    )
    signing_input: str = Field(
        description=(
            "The exact UTF-8 string the signature covers. Verify over these "
            "bytes verbatim; do not re-serialize the parsed object."
        )
    )
    signature: str = Field(description="Base64 Ed25519 signature over signing_input.")
    keys_url: str = Field(description="Where to fetch the public key for `kid`.")


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
