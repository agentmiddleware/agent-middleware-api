"""Frozen, bounded records for already-authorized operation evidence.

These types carry a wallet projection; they do not authorize or fetch one.
"""

from __future__ import annotations

from dataclasses import field
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, FiniteFloat, StringConstraints
from pydantic.dataclasses import dataclass


SCHEMA_VERSION: Literal[1] = 1
CLASSIFICATION_VERSION: Literal[1] = 1
_FROZEN = ConfigDict(
    frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be aware UTC")
    return value


UtcDateTime = Annotated[datetime, AfterValidator(_utc)]
SafeId = Annotated[
    str, StringConstraints(pattern=r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\z")
]
ReasonCode = Annotated[
    str, StringConstraints(pattern=r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\z")
]
NonnegativeCount = Annotated[int, Field(ge=0)]
NonnegativeFloat = Annotated[FiniteFloat, Field(ge=0)]

TimeBasis = Literal["ingress", "first_observed_evidence"]
AccountClass = Literal["eligible", "internal", "demo", "CI", "monitoring", "unknown"]
MappedAccountClass = Literal["eligible", "internal", "demo", "CI", "monitoring"]
MappingStatus = Literal["mapped", "unmapped", "undated", "ambiguous", "wallet_unknown"]
CorrelationStatus = Literal["explicit", "ambiguous", "unavailable"]
GatewayOutcome = Literal["succeeded", "failed", "denied", "unknown", "conflicting"]
EffectState = Literal["confirmed", "no_effect_proven", "unknown", "conflicting"]
RecoveryState = Literal[
    "completed", "failed", "pending", "not_applicable", "unknown", "conflicting"
]
FailureClass = Literal[
    "unexpected_fault", "expected_denial", "none", "unknown", "conflicting"
]
Completeness = Literal["complete", "partial", "unknown"]
NextAction = Literal["inspect", "reconcile", "manual_review"]


def _check_attribution(
    account_id: str | None, account_class: AccountClass, mapping_status: MappingStatus
) -> None:
    if mapping_status == "mapped":
        if account_id is None or account_class == "unknown":
            raise ValueError("mapped attribution requires an account and known class")
    elif account_id is not None or account_class != "unknown":
        raise ValueError(f"{mapping_status} attribution must remain unknown")


@dataclass(config=_FROZEN)
class Scope:
    """Authorized wallet IDs only; an empty set is not a wildcard."""

    wallet_ids: frozenset[SafeId]


@dataclass(config=_FROZEN)
class Window:
    start: UtcDateTime
    end: UtcDateTime
    time_basis: TimeBasis

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("window start must precede end")


@dataclass(config=_FROZEN)
class Snapshot:
    cutoff: UtcDateTime
    token: SafeId
    atomic: bool
    replica_lag_seconds: NonnegativeFloat | None


@dataclass(config=_FROZEN)
class Limits:
    page_size: Annotated[int, Field(ge=1, le=1000)] = 1000
    operations: Annotated[int, Field(ge=1, le=100000)] = 100000
    seconds: Annotated[int, Field(ge=1, le=300)] = 300


@dataclass(config=_FROZEN)
class EvidenceRef:
    source: SafeId
    source_id: SafeId
    wallet_id: SafeId | None


@dataclass(config=_FROZEN)
class StageTimestamp:
    stage: ReasonCode
    at: UtcDateTime
    source: SafeId
    source_id: SafeId


@dataclass(config=_FROZEN)
class EvidenceStateFacts:
    """Observed source facts, without inferred recovery.

    Ledger booleans are True only after exact EvidenceRef-linked rows are checked
    in the same authorized snapshot: wallet, action, operation key, correlation,
    and amount as applicable. False records a mismatch; None is unverified.
    """

    gateway_outcome: GatewayOutcome | None = None
    effect_state: EffectState | None = None
    refund_state: RecoveryState | None = None
    budget_release_state: RecoveryState | None = None
    dispatch_state: (
        Literal[
            "prepared",
            "dispatched",
            "dispatch_claimed",
            "succeeded",
            "returned_error",
            "delivery_uncertain",
            "response_rejected",
            "unknown",
            "conflicting",
        ]
        | None
    ) = None
    policy_decision: Literal["allow", "deny", "unknown", "conflicting"] | None = None
    permit_status: Literal["active", "revoked", "unknown"] | None = None
    permit_expires_at: UtcDateTime | None = None
    permit_revoked_at: UtcDateTime | None = None
    approval_status: (
        Literal["pending", "approved", "rejected", "expired", "consumed", "unknown"]
        | None
    ) = None
    approval_expires_at: UtcDateTime | None = None
    approval_decided_at: UtcDateTime | None = None
    permit_request_status: (
        Literal[
            "pending", "minting", "approved", "rejected", "expired", "failed", "unknown"
        ]
        | None
    ) = None
    idempotency_outcome: Literal[
        "new", "replayed", "in_progress", "payload_mismatch", "unknown"
    ] = "unknown"
    ledger_action: Literal["debit", "refund", "other", "unknown"] | None = None
    ledger_link_verified: bool | None = None
    refund_amount_matches_debit: bool | None = None


@dataclass(config=_FROZEN)
class Evidence:
    source: SafeId
    source_id: SafeId
    wallet_id: SafeId | None
    edges: tuple[EvidenceRef, ...] = ()
    stage_timestamps: tuple[StageTimestamp, ...] = ()
    request_id: SafeId | None = None
    attempt_id: SafeId | None = None
    logical_operation_id: SafeId | None = None
    tool: SafeId | None = None
    occurred_at: UtcDateTime | None = None
    ingested_at: UtcDateTime | None = None
    reason_code: ReasonCode | None = None
    state_facts: EvidenceStateFacts = field(default_factory=EvidenceStateFacts)


@dataclass(config=_FROZEN)
class SourceCoverage:
    source: SafeId
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    earliest_retained_at: UtcDateTime | None = None
    enumeration_complete: bool = False
    truncated: bool = False
    event_lag_seconds: NonnegativeFloat | None = None
    consistency_flags: tuple[ReasonCode, ...] = ()
    skew_flags: tuple[ReasonCode, ...] = ()
    gaps: tuple[ReasonCode, ...] = ()


@dataclass(config=_FROZEN)
class Coverage:
    sources: tuple[SourceCoverage, ...]
    enumeration_complete: bool = False
    truncated: bool = False
    consistency_flags: tuple[ReasonCode, ...] = ()
    skew_flags: tuple[ReasonCode, ...] = ()
    gaps: tuple[ReasonCode, ...] = ()


@dataclass(config=_FROZEN)
class EvidenceBatch:
    rows: tuple[Evidence, ...]
    snapshot: Snapshot
    coverage: Coverage


@dataclass(config=_FROZEN)
class MappingInterval:
    wallet_id: SafeId
    account_id: SafeId
    account_class: MappedAccountClass
    effective_from: UtcDateTime
    effective_until: UtcDateTime | None

    def __post_init__(self) -> None:
        if (
            self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must follow effective_from")


@dataclass(config=_FROZEN)
class AccountMapping:
    version: SafeId
    intervals: tuple[MappingInterval, ...]


@dataclass(config=_FROZEN)
class AccountAttribution:
    account_id: SafeId | None
    account_class: AccountClass
    mapping_status: MappingStatus

    def __post_init__(self) -> None:
        _check_attribution(self.account_id, self.account_class, self.mapping_status)


@dataclass(config=_FROZEN)
class Operation:
    operation_id: SafeId
    wallet_id: SafeId | None
    time_basis: TimeBasis
    request_ids: tuple[SafeId, ...] = ()
    attempt_ids: tuple[SafeId, ...] = ()
    logical_operation_id: SafeId | None = None
    correlation_status: CorrelationStatus = "unavailable"
    account_id: SafeId | None = None
    account_class: AccountClass = "unknown"
    mapping_status: MappingStatus = "unmapped"
    tool: SafeId | None = None
    first_seen_at: UtcDateTime | None = None
    last_seen_at: UtcDateTime | None = None
    stage_timestamps: tuple[StageTimestamp, ...] = ()
    gateway_outcome: GatewayOutcome = "unknown"
    reason_code: ReasonCode | None = None
    failure_class: FailureClass = "unknown"
    failure_stage: ReasonCode | None = None
    effect_state: EffectState = "unknown"
    refund_state: RecoveryState = "unknown"
    budget_release_state: RecoveryState = "unknown"
    unresolved_since: UtcDateTime | None = None
    server_release: SafeId | None = None
    deployment: SafeId | None = None
    client_version: SafeId | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    evidence_gaps: tuple[ReasonCode, ...] = ()
    conflicts: tuple[ReasonCode, ...] = ()
    next_action: NextAction = "inspect"
    execution_intent: bool | None = None
    replay_only: bool | None = None
    observed_fault: bool | None = None
    observed_denial: bool | None = None

    def __post_init__(self) -> None:
        if self.wallet_id is None:
            if self.mapping_status == "unmapped":
                object.__setattr__(self, "mapping_status", "wallet_unknown")
            elif self.mapping_status != "wallet_unknown":
                raise ValueError("wallet_unknown requires unknown mapping status")
        elif self.mapping_status == "wallet_unknown":
            raise ValueError("wallet_unknown requires a null wallet_id")
        _check_attribution(self.account_id, self.account_class, self.mapping_status)


@dataclass(config=_FROZEN)
class Metric:
    name: ReasonCode
    count: NonnegativeCount
    numerator: NonnegativeCount | None
    denominator: NonnegativeCount | None
    ratio: NonnegativeFloat | None
    grain: ReasonCode
    window: Window
    unknown_count: NonnegativeCount
    excluded_count: NonnegativeCount
    completeness: Completeness

    def __post_init__(self) -> None:
        if self.denominator == 0 and self.ratio is not None:
            raise ValueError("zero denominator requires a null ratio")


@dataclass(config=_FROZEN)
class Report:
    report_id: SafeId
    generated_at: UtcDateTime
    as_of: UtcDateTime
    snapshot_cutoff: UtcDateTime
    window_start: UtcDateTime
    window_end: UtcDateTime
    time_basis: TimeBasis
    environment: SafeId | None
    source_release: SafeId | None
    coverage: Coverage
    mapping_version: SafeId
    exclusions: tuple[ReasonCode, ...]
    operations: tuple[Operation, ...]
    evidence: tuple[Evidence, ...]
    metrics: tuple[Metric, ...]
    schema_version: Literal[1] = SCHEMA_VERSION
    classification_version: Literal[1] = CLASSIFICATION_VERSION

    def __post_init__(self) -> None:
        Window(self.window_start, self.window_end, self.time_basis)
        if self.as_of != self.window_end:
            raise ValueError("as_of must equal window_end")
        if any(
            operation.time_basis != self.time_basis for operation in self.operations
        ):
            raise ValueError("operation time_basis must match report time_basis")
        if any(metric.window.time_basis != self.time_basis for metric in self.metrics):
            raise ValueError("metric time_basis must match report time_basis")


@dataclass(config=_FROZEN)
class ArtifactFile:
    name: SafeId
    sha256: Annotated[str, StringConstraints(pattern=r"\A[a-f0-9]{64}\z")]
    row_count: NonnegativeCount
    completeness: Completeness


@dataclass(config=_FROZEN)
class ArtifactManifest:
    report_id: SafeId
    files: tuple[ArtifactFile, ...]
    completeness: Completeness
