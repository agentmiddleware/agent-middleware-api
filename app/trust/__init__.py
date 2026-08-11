"""The trust plane — the frozen product spine of Agent Middleware API.

This package is a stable, import-light boundary over the trust-plane primitives
that constitute the core product:

    permits -> governed invocation -> idempotency -> wallet ledger (metering)
    -> receipts -> audit verification -> evidence

Everything outside this boundary is a protocol adapter or an example workload.
The modules here re-export the canonical implementations that live under
``app.services`` / ``app.policy`` so callers can depend on the product core
through one obvious namespace without coupling to internal module layout.

This is a facade, not a fork: it re-exports rather than reimplements. One
exception is worth naming plainly: ``McpGovernedAdapter`` (in ``.adapters``)
delegates the governed-invocation orchestration itself to
``app.routers.mcp._execute_registered_tool`` — that orchestration is not
duplicated under ``app.services`` today. See ``tests/test_trust_boundary.py``
and ``adapters.py`` for the documented reasoning.
"""

from __future__ import annotations

from .adapters import (
    GovernedInvocationAdapter,
    GovernedRequest,
    GovernedResult,
    McpGovernedAdapter,
)
from .approvals import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_EXPIRED,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_REJECTED,
    ApprovalCheck,
    HumanApprovalError,
    HumanApprovalService,
    HumanApprovalUnavailableError,
    get_human_approval_service,
    human_approval_available,
    human_approval_configured,
)
from .audit_chain import (
    AuditChainVerification,
    audit_payload,
    count_audit_events,
    list_audit_events,
    record_audit_event,
    sign_audit_model,
    summarize_audit_events,
    verify_audit_chain,
)
from .evidence import (
    authorize_receipt_access,
    build_evidence_bundle,
    build_receipt_evidence,
)
from .idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    IdempotencyBegin,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    IdempotencyService,
    get_idempotency_service,
)
from .metering import (
    DEFAULT_PRICING,
    AgentMoney,
    InsufficientFundsError,
    KYCVerificationRequiredError,
    WalletNotFoundError,
    get_agent_money,
)
from .permits import (
    PermitError,
    PermitService,
    PermitValidation,
    get_permit_service,
    permit_model_to_response,
)
from .policy import (
    PolicyDecision,
    PolicyEvaluation,
    evaluate_governed_action,
    evaluate_tool_invocation,
    evaluate_wallet_policy,
    record_governed_action,
)
from .receipts import ReceiptError, ReceiptService, get_receipt_service
from .refund_reconciliation import (
    RefundReconciliationError,
    RefundReconciliationService,
    build_pending_refund_reconciliation,
    get_refund_reconciliation_service,
)
from .signing import (
    RECEIPT_CANONICALIZATION,
    SigningKeyError,
    SigningKeyService,
    canonical_json,
    get_signing_key_service,
    sha256_hex,
)

__all__ = [
    # adapters
    "GovernedInvocationAdapter",
    "GovernedRequest",
    "GovernedResult",
    "McpGovernedAdapter",
    # human approval gate
    "APPROVAL_STATUS_APPROVED",
    "APPROVAL_STATUS_EXPIRED",
    "APPROVAL_STATUS_PENDING",
    "APPROVAL_STATUS_REJECTED",
    "ApprovalCheck",
    "HumanApprovalError",
    "HumanApprovalService",
    "HumanApprovalUnavailableError",
    "get_human_approval_service",
    "human_approval_available",
    "human_approval_configured",
    # permits
    "PermitService",
    "PermitValidation",
    "PermitError",
    "get_permit_service",
    "permit_model_to_response",
    # receipts
    "ReceiptService",
    "ReceiptError",
    "get_receipt_service",
    # failed-refund reconciliation
    "RefundReconciliationError",
    "RefundReconciliationService",
    "build_pending_refund_reconciliation",
    "get_refund_reconciliation_service",
    # signing (cryptographic root)
    "RECEIPT_CANONICALIZATION",
    "SigningKeyService",
    "SigningKeyError",
    "get_signing_key_service",
    "canonical_json",
    "sha256_hex",
    # idempotency
    "GOVERNED_MCP_IDEMPOTENCY_ENDPOINT",
    "IdempotencyBegin",
    "IdempotencyService",
    "IdempotencyReplay",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "get_idempotency_service",
    # audit
    "verify_audit_chain",
    "sign_audit_model",
    "audit_payload",
    "AuditChainVerification",
    "record_audit_event",
    "list_audit_events",
    "count_audit_events",
    "summarize_audit_events",
    # policy
    "evaluate_tool_invocation",
    "evaluate_governed_action",
    "evaluate_wallet_policy",
    "record_governed_action",
    "PolicyDecision",
    "PolicyEvaluation",
    # metering
    "AgentMoney",
    "get_agent_money",
    "DEFAULT_PRICING",
    "InsufficientFundsError",
    "KYCVerificationRequiredError",
    "WalletNotFoundError",
    # evidence
    "authorize_receipt_access",
    "build_receipt_evidence",
    "build_evidence_bundle",
]
