"""Frozen, bounded records for already-authorized operation evidence.

These types carry a wallet projection; they do not authorize or fetch one.
"""

from __future__ import annotations

from dataclasses import InitVar, field
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
RequestDisposition = Literal[
    "execution_intent",
    "same_key_replay",
    "status_read",
    "non_execution_read",
    "unknown",
]
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
class AuthorizedOwnershipEpoch:
    wallet_id: SafeId
    ownership_epoch_id: SafeId
    evidence_from: UtcDateTime
    evidence_until: UtcDateTime

    def __post_init__(self) -> None:
        if self.evidence_from >= self.evidence_until:
            raise ValueError("evidence_until must follow evidence_from")


@dataclass(config=_FROZEN)
class Scope:
    """Explicit wallet epochs only; wallet IDs alone grant no evidence history."""

    wallet_ids: frozenset[SafeId]
    authorized_ownership_epochs: tuple[AuthorizedOwnershipEpoch, ...] = ()
    allow_unknown_wallet_counts: bool = False

    def __post_init__(self) -> None:
        if any(
            epoch.wallet_id not in self.wallet_ids
            for epoch in self.authorized_ownership_epochs
        ):
            raise ValueError("ownership epoch wallet must be in scope")


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
    ownership_epoch_id: SafeId | None = None
    original_operation_anchor_id: SafeId | None = None


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
    event_kind: Literal["ingress", "terminal", "attempt"] | None = None
    request_disposition: RequestDisposition | None = None
    ownership_epoch_id: SafeId | None = None
    original_operation_anchor_id: SafeId | None = None

    def __post_init__(self) -> None:
        if self.event_kind == "attempt" and self.request_disposition in (
            "same_key_replay",
            "status_read",
            "non_execution_read",
        ):
            raise ValueError("attempt event cannot represent a nonexecution request")


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
    window_ingress: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        if any(
            row.event_kind != "ingress"
            or row.wallet_id is None
            or row.ownership_epoch_id is None
            or row.original_operation_anchor_id is None
            or row.request_id is None
            or row.occurred_at is None
            or row.request_disposition is None
            for row in self.window_ingress
        ):
            raise ValueError("window_ingress requires identified ingress evidence")


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
class IngressObservation:
    request_id: SafeId
    occurred_at: UtcDateTime
    disposition: RequestDisposition


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
    ownership_epoch_id: SafeId | None = None
    original_operation_anchor_id: SafeId | None = None
    ingress_observations: tuple[IngressObservation, ...] = ()

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
class UnknownWalletCount:
    status: Literal["complete", "not_authorized", "unavailable", "partial"] = (
        "not_authorized"
    )
    count: NonnegativeCount | None = None
    bucket_start: UtcDateTime | None = None
    bucket_end: UtcDateTime | None = None

    def __post_init__(self) -> None:
        if self.status == "complete":
            if self.count is None:
                raise ValueError("complete unknown-wallet aggregate requires count")
            if self.bucket_start is None or self.bucket_end is None:
                raise ValueError("complete unknown-wallet aggregate requires bucket")
        elif self.count is not None:
            raise ValueError("incomplete unknown-wallet aggregate requires null count")
        if (self.bucket_start is None) != (self.bucket_end is None):
            raise ValueError("unknown-wallet bucket requires both boundaries")
        if self.bucket_start is not None and self.bucket_end is not None:
            if (
                self.bucket_start.time() != datetime.min.time()
                or self.bucket_end.time() != datetime.min.time()
                or self.bucket_end - self.bucket_start
                not in (timedelta(days=7), timedelta(days=30))
            ):
                raise ValueError("unknown-wallet bucket must be 7 or 30 full UTC days")


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
    unknown_wallet_aggregate: UnknownWalletCount = field(
        default_factory=UnknownWalletCount
    )
    authorized_scope: InitVar[Scope | None] = None

    def __post_init__(self, authorized_scope: Scope | None) -> None:
        Window(self.window_start, self.window_end, self.time_basis)
        if self.as_of != self.window_end:
            raise ValueError("as_of must equal window_end")
        if any(
            operation.time_basis != self.time_basis for operation in self.operations
        ):
            raise ValueError("operation time_basis must match report time_basis")
        if any(metric.window.time_basis != self.time_basis for metric in self.metrics):
            raise ValueError("metric time_basis must match report time_basis")
        if self.time_basis == "first_observed_evidence" and (
            any(evidence.event_kind == "ingress" for evidence in self.evidence)
            or any(operation.ingress_observations for operation in self.operations)
        ):
            raise ValueError(
                "historical time_basis cannot include ingress observations"
            )
        if (
            self.unknown_wallet_aggregate.bucket_end is not None
            and self.unknown_wallet_aggregate.bucket_end
            != self.as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        ):
            raise ValueError("unknown_wallet_aggregate bucket_end must match as_of day")
        bucket = self.unknown_wallet_aggregate
        if (
            bucket.bucket_start is not None
            and bucket.bucket_end is not None
            and bucket.bucket_end - bucket.bucket_start
            != self.window_end - self.window_start
        ):
            raise ValueError(
                "unknown_wallet_aggregate bucket window must match report window"
            )
        if bucket.status == "complete":
            if (
                bucket.bucket_end is not None
                and bucket.bucket_end > self.snapshot_cutoff
            ):
                raise ValueError(
                    "unknown_wallet_aggregate bucket_end exceeds snapshot_cutoff"
                )
        if any(operation.wallet_id is None for operation in self.operations) or any(
            evidence.wallet_id is None for evidence in self.evidence
        ):
            raise ValueError("report rows require wallet_id")
        if any(
            ref.wallet_id is None
            for operation in self.operations
            for ref in operation.evidence_refs
        ) or any(
            edge.wallet_id is None
            for evidence in self.evidence
            for edge in evidence.edges
        ):
            raise ValueError("report evidence refs require wallet_id")
        evidence_ids = {
            (
                evidence.source,
                evidence.source_id,
                evidence.wallet_id,
                evidence.ownership_epoch_id,
                evidence.original_operation_anchor_id,
            )
            for evidence in self.evidence
        }
        if any(
            ref.wallet_id != operation.wallet_id
            or ref.ownership_epoch_id != operation.ownership_epoch_id
            or ref.original_operation_anchor_id
            != operation.original_operation_anchor_id
            or (
                ref.source,
                ref.source_id,
                ref.wallet_id,
                ref.ownership_epoch_id,
                ref.original_operation_anchor_id,
            )
            not in evidence_ids
            for operation in self.operations
            for ref in operation.evidence_refs
        ) or any(
            edge.wallet_id != evidence.wallet_id
            or edge.ownership_epoch_id != evidence.ownership_epoch_id
            or edge.original_operation_anchor_id
            != evidence.original_operation_anchor_id
            or (
                edge.source,
                edge.source_id,
                edge.wallet_id,
                edge.ownership_epoch_id,
                edge.original_operation_anchor_id,
            )
            not in evidence_ids
            for evidence in self.evidence
            for edge in evidence.edges
        ):
            raise ValueError("report evidence ref must match scoped evidence wallet")
        if any(
            (
                stage.source,
                stage.source_id,
                operation.wallet_id,
                operation.ownership_epoch_id,
                operation.original_operation_anchor_id,
            )
            not in evidence_ids
            for operation in self.operations
            for stage in operation.stage_timestamps
        ) or any(
            (
                stage.source,
                stage.source_id,
                evidence.wallet_id,
                evidence.ownership_epoch_id,
                evidence.original_operation_anchor_id,
            )
            not in evidence_ids
            for evidence in self.evidence
            for stage in evidence.stage_timestamps
        ):
            raise ValueError("report stage timestamp must match scoped evidence wallet")
        if authorized_scope is None:
            raise ValueError("report requires authorized_scope")
        if (
            bucket.status in ("complete", "partial")
            and not authorized_scope.allow_unknown_wallet_counts
        ):
            raise ValueError(
                "unknown wallet aggregate requires allow_unknown_wallet_counts"
            )
        if self.operations or self.evidence:
            if any(
                operation.ownership_epoch_id is None
                or operation.original_operation_anchor_id is None
                for operation in self.operations
            ) or any(
                evidence.ownership_epoch_id is None
                or evidence.original_operation_anchor_id is None
                for evidence in self.evidence
            ):
                raise ValueError("raw report rows require original provenance")
            if any(
                ref.ownership_epoch_id is None
                or ref.original_operation_anchor_id is None
                for operation in self.operations
                for ref in operation.evidence_refs
            ) or any(
                edge.ownership_epoch_id is None
                or edge.original_operation_anchor_id is None
                for evidence in self.evidence
                for edge in evidence.edges
            ):
                raise ValueError("report evidence ref requires original provenance")
            authorized_epochs = {
                (epoch.wallet_id, epoch.ownership_epoch_id)
                for epoch in authorized_scope.authorized_ownership_epochs
            }
            if any(
                (operation.wallet_id, operation.ownership_epoch_id)
                not in authorized_epochs
                for operation in self.operations
            ) or any(
                (evidence.wallet_id, evidence.ownership_epoch_id)
                not in authorized_epochs
                for evidence in self.evidence
            ):
                raise ValueError("raw report rows exceed authorized_scope epochs")
        if self.time_basis == "ingress":
            ingress_evidence = {
                (
                    evidence.wallet_id,
                    evidence.ownership_epoch_id,
                    evidence.original_operation_anchor_id,
                    evidence.request_id,
                    evidence.occurred_at,
                    evidence.request_disposition,
                )
                for evidence in self.evidence
                if evidence.event_kind == "ingress"
            }
            for operation in self.operations:
                if not any(
                    observation.disposition == "execution_intent"
                    for observation in operation.ingress_observations
                ):
                    raise ValueError(
                        "ingress observation requires execution_intent anchor"
                    )
                for observation in operation.ingress_observations:
                    if (
                        operation.wallet_id,
                        operation.ownership_epoch_id,
                        operation.original_operation_anchor_id,
                        observation.request_id,
                        observation.occurred_at,
                        observation.disposition,
                    ) not in ingress_evidence:
                        raise ValueError(
                            "ingress observation must match scoped ingress evidence"
                        )


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
