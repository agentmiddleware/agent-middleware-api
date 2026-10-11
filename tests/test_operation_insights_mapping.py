"""Offline account attribution and contract boundaries for operation insights."""

import json
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timezone
from math import nan

import pytest
from pydantic import ValidationError

from app.services.operation_insights.contracts import (
    AccountAttribution,
    AccountMapping,
    Coverage,
    Evidence,
    EvidenceBatch,
    EvidenceRef,
    EvidenceStateFacts,
    Limits,
    MappingInterval,
    Metric,
    Operation,
    Report,
    ArtifactManifest,
    Scope,
    Snapshot,
    StageTimestamp,
    TimeBasis,
    Window,
)
from app.services.operation_insights.mapping import attribute


def utc(day: int) -> datetime:
    return datetime(2026, 10, day, tzinfo=timezone.utc)


def test_migration_uses_half_open_effective_dates() -> None:
    mapping = AccountMapping(
        version="v1",
        intervals=(
            MappingInterval("wallet-1", "account-old", "eligible", utc(1), utc(5)),
            MappingInterval("wallet-1", "account-new", "eligible", utc(5), None),
        ),
    )

    before = attribute("wallet-1", utc(4), mapping)
    boundary = attribute("wallet-1", utc(5), mapping)

    assert before.account_id == "account-old"
    assert boundary.account_id == "account-new"
    assert boundary.mapping_status == "mapped"


def test_overlapping_intervals_are_ambiguous_even_when_account_matches() -> None:
    mapping = AccountMapping(
        version="v1",
        intervals=(
            MappingInterval("wallet-1", "account-1", "eligible", utc(1), None),
            MappingInterval("wallet-1", "account-1", "eligible", utc(3), None),
        ),
    )

    result = attribute("wallet-1", utc(4), mapping)

    assert result.account_id is None
    assert result.account_class == "unknown"
    assert result.mapping_status == "ambiguous"


def test_unmapped_wallet_and_missing_time_stay_unknown() -> None:
    mapping = AccountMapping(
        version="v1",
        intervals=(MappingInterval("wallet-1", "account-1", "eligible", utc(1), None),),
    )

    unmapped = attribute("wallet-missing", utc(4), mapping)
    undated = attribute("wallet-1", None, mapping)

    assert unmapped.account_id is None
    assert unmapped.account_class == "unknown"
    assert unmapped.mapping_status == "unmapped"
    assert undated.account_id is None
    assert undated.account_class == "unknown"
    assert undated.mapping_status == "undated"


@pytest.mark.parametrize("account_class", ["internal", "demo", "CI", "monitoring"])
def test_explicit_non_customer_classes_remain_excluded(account_class: str) -> None:
    mapping = AccountMapping(
        version="v1",
        intervals=(
            MappingInterval("wallet-1", "account-1", account_class, utc(1), None),
        ),
    )

    result = attribute("wallet-1", utc(4), mapping)

    assert result.account_id == "account-1"
    assert result.account_class == account_class
    assert result.mapping_status == "mapped"


def test_wallet_match_is_exact_and_does_not_inherit_parent_or_prefix() -> None:
    mapping = AccountMapping(
        version="v1",
        intervals=(MappingInterval("wallet-1", "account-1", "eligible", utc(1), None),),
    )

    child = attribute("wallet-1-child", utc(4), mapping)

    assert child.account_id is None
    assert child.mapping_status == "unmapped"


def test_mapping_and_scope_are_immutable() -> None:
    mapping = AccountMapping(version="v1", intervals=())
    scope = Scope(wallet_ids=frozenset({"wallet-1"}))

    with pytest.raises(FrozenInstanceError):
        mapping.version = "v2"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        scope.wallet_ids = frozenset({"wallet-2"})  # type: ignore[misc]


def test_contracts_reject_naive_or_non_utc_times() -> None:
    with pytest.raises(ValueError, match="UTC"):
        Window(datetime(2026, 10, 1), utc(2), "ingress")
    with pytest.raises(ValueError, match="UTC"):
        MappingInterval(
            "wallet-1", "account-1", "eligible", datetime(2026, 10, 1), None
        )


def test_evidence_rejects_unbounded_reason_and_arbitrary_metadata() -> None:
    with pytest.raises(ValueError, match="reason_code"):
        Evidence(
            source="audit",
            source_id="event-1",
            wallet_id="wallet-1",
            reason_code="raw error with client detail",
        )
    with pytest.raises(ValidationError, match="metadata"):
        Evidence(
            source="audit",
            source_id="event-1",
            wallet_id="wallet-1",
            metadata={"key": "secret"},
        )
    with pytest.raises(ValidationError, match="state_facts"):
        Evidence(
            "audit", "event-1", "wallet-1", state_facts={"Authorization": "secret"}
        )  # type: ignore[arg-type]


def test_receipt_reason_code_preserves_128_character_source_bound() -> None:
    evidence = Evidence("receipt", "receipt-1", "wallet-1", reason_code="a" * 128)

    assert evidence.reason_code == "a" * 128
    with pytest.raises(ValidationError, match="reason_code"):
        Evidence("receipt", "receipt-2", "wallet-1", reason_code="a" * 129)


def test_rejected_source_content_is_absent_from_validation_errors() -> None:
    sentinel = "raw secret error text"

    with pytest.raises(ValidationError, match="reason_code") as error:
        Evidence("receipt", "receipt-1", "wallet-1", reason_code=sentinel)

    assert sentinel not in str(error.value)


def test_snapshot_and_coverage_keep_partial_state_explicit() -> None:
    snapshot = Snapshot(utc(5), "snapshot-1", False, None)
    coverage = Coverage(sources=(), truncated=True, gaps=("receipt_unavailable",))
    evidence = Evidence(
        source="audit",
        source_id="event-1",
        wallet_id="wallet-1",
        state_facts=EvidenceStateFacts(
            gateway_outcome="unknown", effect_state="unknown"
        ),
    )
    batch = EvidenceBatch((evidence,), snapshot, coverage)

    assert batch.coverage.truncated is True
    assert batch.snapshot.atomic is False
    assert batch.rows[0].state_facts.effect_state == "unknown"
    assert Limits() == Limits(page_size=1000, operations=100000, seconds=300)


def test_historical_dispatch_state_remains_a_bounded_fact() -> None:
    facts = EvidenceStateFacts(dispatch_state="dispatched")

    assert facts.dispatch_state == "dispatched"


def test_report_envelope_has_explicit_window_fields() -> None:
    report = Report(
        report_id="report-1",
        generated_at=utc(5),
        as_of=utc(5),
        snapshot_cutoff=utc(5),
        window_start=utc(1),
        window_end=utc(5),
        time_basis="first_observed_evidence",
        environment=None,
        source_release=None,
        coverage=Coverage(sources=()),
        mapping_version="v1",
        exclusions=("demo",),
        operations=(),
        evidence=(),
        metrics=(),
        authorized_scope=Scope(wallet_ids=frozenset()),
    )

    assert asdict(report)["window_start"] == utc(1)
    assert asdict(report)["time_basis"] == "first_observed_evidence"
    assert report.schema_version == 1
    assert report.classification_version == 1
    assert asdict(report)["unknown_wallet_aggregate"] == {
        "status": "not_authorized",
        "count": None,
        "bucket_start": None,
        "bucket_end": None,
    }
    assert "authorized_scope" not in asdict(report)


def test_operation_keeps_gateway_effect_and_recovery_independent() -> None:
    operation = Operation(
        "operation-1",
        "wallet-1",
        "first_observed_evidence",
        gateway_outcome="succeeded",
        effect_state="unknown",
        refund_state="completed",
        budget_release_state="unknown",
    )

    assert operation.gateway_outcome == "succeeded"
    assert operation.effect_state == "unknown"
    assert operation.refund_state == "completed"
    assert operation.budget_release_state == "unknown"


def test_nested_contract_collections_cannot_be_mutable_lists() -> None:
    snapshot = Snapshot(utc(5), "snapshot-1", False, None)
    coverage = Coverage(sources=())
    evidence = Evidence("audit", "event-1", "wallet-1")
    ref = EvidenceRef("audit", "event-1", "wallet-1")

    with pytest.raises(ValidationError, match="rows"):
        EvidenceBatch(rows=[evidence], snapshot=snapshot, coverage=coverage)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="evidence_refs"):
        Operation("operation-1", "wallet-1", "ingress", evidence_refs=[ref])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="operations"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=coverage,
            mapping_version="v1",
            exclusions=(),
            operations=[],
            evidence=(),
            metrics=(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="files"):
        ArtifactManifest(report_id="report-1", files=[], completeness="unknown")  # type: ignore[arg-type]


def test_nested_contract_records_reject_arbitrary_dictionaries() -> None:
    snapshot = Snapshot(utc(5), "snapshot-1", False, None)
    coverage = Coverage(sources=())

    with pytest.raises(ValidationError, match="snapshot"):
        EvidenceBatch(rows=(), snapshot={"token": "secret"}, coverage=coverage)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="window"):
        Metric(
            name="requests",
            count=1,
            numerator=1,
            denominator=1,
            ratio=1.0,
            grain="request",
            window={"unexpected": "value"},
            unknown_count=0,
            excluded_count=0,
            completeness="complete",
        )  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="coverage"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage={"unexpected": "value"},
            mapping_version="v1",
            exclusions=(),
            operations=(),
            evidence=(),
            metrics=(),  # type: ignore[arg-type]
        )
    assert snapshot.atomic is False


def test_operation_rejects_invalid_state_and_nonboolean_counting_flags() -> None:
    with pytest.raises(ValueError, match="gateway_outcome"):
        Operation(
            "operation-1",
            "wallet-1",
            "ingress",
            gateway_outcome={"unexpected": "value"},
        )  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="execution_intent"):
        Operation("operation-1", "wallet-1", "ingress", execution_intent="false")  # type: ignore[arg-type]


def test_nonfinite_lag_and_ratio_are_rejected() -> None:
    with pytest.raises(ValidationError, match="replica_lag_seconds"):
        Snapshot(
            cutoff=utc(5), token="snapshot-1", atomic=False, replica_lag_seconds=nan
        )
    with pytest.raises(ValidationError, match="ratio"):
        Metric(
            name="requests",
            count=1,
            numerator=1,
            denominator=1,
            ratio=nan,
            grain="request",
            window=Window(utc(1), utc(5), "ingress"),
            unknown_count=0,
            excluded_count=0,
            completeness="complete",
        )


def test_walletless_evidence_and_operation_round_trip_as_unknown() -> None:
    evidence = Evidence(
        source="ingress_event",
        source_id="event-1",
        wallet_id=None,
        edges=(EvidenceRef("terminal_event", "event-2", None),),
        occurred_at=utc(1),
    )
    operation = Operation(
        operation_id="operation-1",
        wallet_id=None,
        time_basis="ingress",
        evidence_refs=(EvidenceRef("ingress_event", "event-1", None),),
        account_id=None,
        account_class="unknown",
        mapping_status="wallet_unknown",
    )
    assert asdict(operation)["wallet_id"] is None
    assert asdict(operation)["mapping_status"] == "wallet_unknown"
    assert asdict(evidence)["wallet_id"] is None
    assert asdict(evidence)["edges"][0]["wallet_id"] is None

    with pytest.raises(ValueError, match="wallet_id"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=Coverage(sources=()),
            mapping_version="v1",
            exclusions=(),
            operations=(operation,),
            evidence=(evidence,),
            metrics=(),
        )


@pytest.mark.parametrize(
    ("operations", "evidence"),
    [
        ((Operation("operation-1", None, "ingress"),), ()),
        ((), (Evidence("audit", "event-1", None),)),
        (
            (
                Operation(
                    "operation-1",
                    "wallet-1",
                    "ingress",
                    evidence_refs=(EvidenceRef("audit", "event-1", None),),
                ),
            ),
            (),
        ),
        (
            (),
            (
                Evidence(
                    "audit",
                    "event-1",
                    "wallet-1",
                    edges=(EvidenceRef("receipt", "receipt-1", None),),
                ),
            ),
        ),
    ],
    ids=["operation", "evidence", "operation_ref", "evidence_edge"],
)
def test_report_rejects_walletless_projection(
    operations: tuple[Operation, ...], evidence: tuple[Evidence, ...]
) -> None:
    with pytest.raises(ValueError, match="wallet_id"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=Coverage(sources=()),
            mapping_version="v1",
            exclusions=(),
            operations=operations,
            evidence=evidence,
            metrics=(),
        )


def test_report_allows_known_wallet_with_unmapped_attribution() -> None:
    from app.services.operation_insights.contracts import (
        AuthorizedOwnershipEpoch,
        IngressObservation,
    )

    provenance = {
        "ownership_epoch_id": "epoch-A",
        "original_operation_anchor_id": "anchor-A",
    }
    report = Report(
        report_id="report-1",
        generated_at=utc(5),
        as_of=utc(5),
        snapshot_cutoff=utc(5),
        window_start=utc(1),
        window_end=utc(5),
        time_basis="ingress",
        environment=None,
        source_release=None,
        coverage=Coverage(sources=()),
        mapping_version="v1",
        exclusions=(),
        authorized_scope=Scope(
            frozenset({"wallet-1"}),
            authorized_ownership_epochs=(
                AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(5)),
            ),
        ),
        operations=(
            Operation(
                "operation-1",
                "wallet-1",
                "ingress",
                evidence_refs=(
                    EvidenceRef("audit", "event-1", "wallet-1", **provenance),
                ),
                stage_timestamps=(
                    StageTimestamp("authorized", utc(1), "audit", "event-1"),
                ),
                ingress_observations=(
                    IngressObservation("request-1", utc(1), "execution_intent"),
                ),
                **provenance,
            ),
        ),
        evidence=(
            Evidence(
                "ingress_event",
                "ingress-1",
                "wallet-1",
                event_kind="ingress",
                request_id="request-1",
                occurred_at=utc(1),
                request_disposition="execution_intent",
                **provenance,
            ),
            Evidence(
                "audit",
                "event-1",
                "wallet-1",
                edges=(EvidenceRef("receipt", "receipt-1", "wallet-1", **provenance),),
                stage_timestamps=(
                    StageTimestamp("receipted", utc(2), "receipt", "receipt-1"),
                ),
                **provenance,
            ),
            Evidence("receipt", "receipt-1", "wallet-1", **provenance),
        ),
        metrics=(),
    )

    assert report.operations[0].mapping_status == "unmapped"
    assert report.evidence[0].wallet_id == "wallet-1"


@pytest.mark.parametrize(
    ("operations", "evidence"),
    [
        (
            (
                Operation(
                    "operation-1",
                    "wallet-1",
                    "ingress",
                    evidence_refs=(EvidenceRef("audit", "missing", "wallet-1"),),
                ),
            ),
            (Evidence("audit", "event-1", "wallet-1"),),
        ),
        (
            (),
            (
                Evidence(
                    "audit",
                    "event-1",
                    "wallet-1",
                    edges=(EvidenceRef("receipt", "missing", "wallet-1"),),
                ),
            ),
        ),
        (
            (
                Operation(
                    "operation-1",
                    "wallet-1",
                    "ingress",
                    evidence_refs=(EvidenceRef("audit", "event-2", "wallet-2"),),
                ),
            ),
            (Evidence("audit", "event-2", "wallet-2"),),
        ),
        (
            (),
            (
                Evidence(
                    "audit",
                    "event-1",
                    "wallet-1",
                    edges=(EvidenceRef("receipt", "receipt-2", "wallet-2"),),
                ),
                Evidence("receipt", "receipt-2", "wallet-2"),
            ),
        ),
    ],
    ids=[
        "operation_dangling",
        "evidence_dangling",
        "operation_cross_wallet",
        "evidence_cross_wallet",
    ],
)
def test_report_rejects_dangling_or_cross_wallet_references(
    operations: tuple[Operation, ...], evidence: tuple[Evidence, ...]
) -> None:
    with pytest.raises(ValueError, match="evidence ref"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=Coverage(sources=()),
            mapping_version="v1",
            exclusions=(),
            operations=operations,
            evidence=evidence,
            metrics=(),
        )


@pytest.mark.parametrize(
    ("operations", "evidence"),
    [
        (
            (
                Operation(
                    "operation-1",
                    "wallet-1",
                    "ingress",
                    stage_timestamps=(
                        StageTimestamp("prepared", utc(1), "dispatch", "missing"),
                    ),
                ),
            ),
            (),
        ),
        (
            (
                Operation(
                    "operation-1",
                    "wallet-1",
                    "ingress",
                    stage_timestamps=(
                        StageTimestamp("prepared", utc(1), "dispatch", "attempt-2"),
                    ),
                ),
            ),
            (Evidence("dispatch", "attempt-2", "wallet-2"),),
        ),
        (
            (),
            (
                Evidence(
                    "audit",
                    "event-1",
                    "wallet-1",
                    stage_timestamps=(
                        StageTimestamp("prepared", utc(1), "dispatch", "missing"),
                    ),
                ),
            ),
        ),
        (
            (),
            (
                Evidence(
                    "audit",
                    "event-1",
                    "wallet-1",
                    stage_timestamps=(
                        StageTimestamp("prepared", utc(1), "dispatch", "attempt-2"),
                    ),
                ),
                Evidence("dispatch", "attempt-2", "wallet-2"),
            ),
        ),
    ],
    ids=[
        "operation_missing",
        "operation_cross_wallet",
        "evidence_missing",
        "evidence_cross_wallet",
    ],
)
def test_report_rejects_missing_or_cross_wallet_stage_timestamps(
    operations: tuple[Operation, ...], evidence: tuple[Evidence, ...]
) -> None:
    with pytest.raises(ValueError, match="stage timestamp"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=Coverage(sources=()),
            mapping_version="v1",
            exclusions=(),
            operations=operations,
            evidence=evidence,
            metrics=(),
        )


def _provenance_report(
    operations: tuple[Operation, ...],
    evidence: tuple[Evidence, ...],
    scope: Scope | None,
    time_basis: TimeBasis = "ingress",
) -> Report:
    return Report(
        report_id="report-1",
        generated_at=utc(8),
        as_of=utc(8),
        snapshot_cutoff=utc(8),
        window_start=utc(1),
        window_end=utc(8),
        time_basis=time_basis,
        environment=None,
        source_release=None,
        coverage=Coverage(sources=()),
        mapping_version="v1",
        exclusions=(),
        operations=operations,
        evidence=evidence,
        metrics=(),
        authorized_scope=scope,
    )


def test_report_requires_scope_and_original_provenance_for_raw_rows() -> None:
    from app.services.operation_insights.contracts import AuthorizedOwnershipEpoch

    scope = Scope(
        frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(5)),
        ),
    )
    evidence = Evidence(
        "audit",
        "event-1",
        "wallet-1",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
    )

    with pytest.raises(ValueError, match="authorized_scope"):
        _provenance_report((), (evidence,), None)
    with pytest.raises(ValueError, match="provenance"):
        _provenance_report(
            (Operation("operation-1", "wallet-1", "ingress"),), (), scope
        )
    with pytest.raises(ValueError, match="provenance"):
        _provenance_report((), (Evidence("audit", "event-1", "wallet-1"),), scope)
    for row in (
        replace(evidence, ownership_epoch_id=None),
        replace(evidence, original_operation_anchor_id=None),
    ):
        with pytest.raises(ValueError, match="provenance"):
            _provenance_report((), (row,), scope)
    with pytest.raises(ValueError, match="evidence ref"):
        _provenance_report(
            (
                Operation(
                    "operation-1",
                    "wallet-1",
                    "ingress",
                    ownership_epoch_id="epoch-A",
                    original_operation_anchor_id="anchor-A",
                    evidence_refs=(EvidenceRef("audit", "event-1", "wallet-1"),),
                ),
            ),
            (evidence,),
            scope,
        )
    with pytest.raises(ValueError, match="authorized_scope"):
        _provenance_report(
            (),
            (
                Evidence(
                    "audit",
                    "event-2",
                    "wallet-1",
                    ownership_epoch_id="epoch-B",
                    original_operation_anchor_id="anchor-B",
                ),
            ),
            scope,
        )
    with pytest.raises(ValueError, match="authorized_scope"):
        _provenance_report(
            (),
            (
                Evidence(
                    "audit",
                    "event-3",
                    "wallet-2",
                    ownership_epoch_id="epoch-B",
                    original_operation_anchor_id="anchor-B",
                ),
            ),
            scope,
        )


def test_same_wallet_transfer_keeps_late_terminal_in_original_epoch() -> None:
    from app.services.operation_insights.contracts import (
        AuthorizedOwnershipEpoch,
        IngressObservation,
    )

    scope_a = Scope(
        frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(5)),
        ),
    )
    ingress = Evidence(
        "ingress_event",
        "event-1",
        "wallet-1",
        occurred_at=utc(2),
        event_kind="ingress",
        request_id="request-1",
        request_disposition="execution_intent",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
    )
    late_terminal = Evidence(
        "terminal_event",
        "event-2",
        "wallet-1",
        occurred_at=utc(6),
        event_kind="terminal",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
    )
    operation = Operation(
        "operation-1",
        "wallet-1",
        "ingress",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
        evidence_refs=(
            EvidenceRef(
                "ingress_event",
                "event-1",
                "wallet-1",
                ownership_epoch_id="epoch-A",
                original_operation_anchor_id="anchor-A",
            ),
            EvidenceRef(
                "terminal_event",
                "event-2",
                "wallet-1",
                ownership_epoch_id="epoch-A",
                original_operation_anchor_id="anchor-A",
            ),
        ),
        stage_timestamps=(
            StageTimestamp("terminal", utc(6), "terminal_event", "event-2"),
        ),
        ingress_observations=(
            IngressObservation("request-1", utc(2), "execution_intent"),
        ),
    )

    report = _provenance_report((operation,), (ingress, late_terminal), scope_a)

    assert report.evidence[1].occurred_at == utc(6)
    assert report.evidence[1].ownership_epoch_id == "epoch-A"


def test_report_rejects_same_wallet_cross_epoch_reference() -> None:
    from app.services.operation_insights.contracts import AuthorizedOwnershipEpoch

    scope = Scope(
        frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(5)),
            AuthorizedOwnershipEpoch("wallet-1", "epoch-B", utc(5), utc(8)),
        ),
    )
    operation = Operation(
        "operation-1",
        "wallet-1",
        "ingress",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
        evidence_refs=(
            EvidenceRef(
                "audit",
                "event-2",
                "wallet-1",
                ownership_epoch_id="epoch-B",
                original_operation_anchor_id="anchor-B",
            ),
        ),
    )
    foreign = Evidence(
        "audit",
        "event-2",
        "wallet-1",
        ownership_epoch_id="epoch-B",
        original_operation_anchor_id="anchor-B",
    )

    with pytest.raises(ValueError, match="evidence ref"):
        _provenance_report((operation,), (foreign,), scope)
    root_with_edge = Evidence(
        "audit",
        "event-1",
        "wallet-1",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
        edges=(
            EvidenceRef(
                "audit",
                "event-2",
                "wallet-1",
                ownership_epoch_id="epoch-B",
                original_operation_anchor_id="anchor-B",
            ),
        ),
    )
    with pytest.raises(ValueError, match="evidence ref"):
        _provenance_report((), (root_with_edge, foreign), scope)
    root_with_stage = replace(
        root_with_edge,
        edges=(),
        stage_timestamps=(StageTimestamp("seen", utc(2), "audit", "event-2"),),
    )
    with pytest.raises(ValueError, match="stage timestamp"):
        _provenance_report((), (root_with_stage, foreign), scope)


@pytest.mark.parametrize("linked", [True, False])
def test_historical_report_rejects_ingress_evidence_with_same_anchor(
    linked: bool,
) -> None:
    from app.services.operation_insights.contracts import AuthorizedOwnershipEpoch

    scope = Scope(
        frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(8)),
        ),
    )
    ref = EvidenceRef(
        "ingress_event",
        "event-1",
        "wallet-1",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
    )
    operation = Operation(
        "operation-1",
        "wallet-1",
        "first_observed_evidence",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
        evidence_refs=(ref,) if linked else (),
    )
    ingress = Evidence(
        "ingress_event",
        "event-1",
        "wallet-1",
        event_kind="ingress",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
    )

    with pytest.raises(ValueError, match="time_basis"):
        _provenance_report((operation,), (ingress,), scope, "first_observed_evidence")


def test_ingress_observations_keep_each_request_on_prior_root_operation() -> None:
    from app.services.operation_insights.contracts import IngressObservation

    previous = IngressObservation("request-1", utc(1), "execution_intent")
    current = IngressObservation("request-2", utc(8), "same_key_replay")
    operation = Operation(
        "operation-1",
        "wallet-1",
        "ingress",
        ingress_observations=(previous, current),
    )

    assert asdict(operation)["ingress_observations"][1]["request_id"] == "request-2"
    assert (
        Operation(
            "historical-1", "wallet-1", "first_observed_evidence"
        ).ingress_observations
        == ()
    )
    with pytest.raises(ValidationError, match="ingress_observations"):
        Operation("operation-2", "wallet-1", "ingress", ingress_observations=[current])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="disposition"):
        IngressObservation(
            request_id="request-3", occurred_at=utc(8), disposition="raw client value"
        )  # type: ignore[arg-type]


def test_ingress_report_requires_backed_execution_intent_observation() -> None:
    from app.services.operation_insights.contracts import (
        AuthorizedOwnershipEpoch,
        IngressObservation,
    )

    scope = Scope(
        frozenset({"wallet-1", "wallet-2"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(8)),
            AuthorizedOwnershipEpoch("wallet-2", "epoch-A", utc(1), utc(8)),
        ),
    )
    ingress = Evidence(
        "ingress_event",
        "event-1",
        "wallet-1",
        request_id="request-1",
        occurred_at=utc(2),
        event_kind="ingress",
        request_disposition="execution_intent",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
    )
    operation = Operation(
        "operation-1",
        "wallet-1",
        "ingress",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
        ingress_observations=(
            IngressObservation("request-1", utc(2), "execution_intent"),
        ),
    )

    assert _provenance_report((operation,), (ingress,), scope).operations == (
        operation,
    )
    with pytest.raises(ValueError, match="ingress observation"):
        _provenance_report(
            (replace(operation, ingress_observations=()),), (ingress,), scope
        )
    with pytest.raises(ValueError, match="execution_intent"):
        _provenance_report(
            (
                replace(
                    operation,
                    ingress_observations=(
                        IngressObservation("request-1", utc(2), "status_read"),
                    ),
                ),
            ),
            (replace(ingress, request_disposition="status_read"),),
            scope,
        )
    for unmatched in (
        replace(ingress, request_id="request-2"),
        replace(ingress, occurred_at=utc(3)),
        replace(ingress, wallet_id="wallet-2"),
        replace(ingress, ownership_epoch_id="epoch-B"),
        replace(ingress, original_operation_anchor_id="anchor-B"),
        replace(ingress, event_kind="terminal"),
        replace(ingress, request_disposition="same_key_replay"),
    ):
        # Keep the foreign epoch authorized so observation matching is the guard.
        matching_scope = Scope(
            frozenset({"wallet-1", "wallet-2"}),
            authorized_ownership_epochs=(
                *scope.authorized_ownership_epochs,
                AuthorizedOwnershipEpoch("wallet-1", "epoch-B", utc(1), utc(8)),
            ),
        )
        with pytest.raises(ValueError, match="ingress observation"):
            _provenance_report((operation,), (unmatched,), matching_scope)
    with pytest.raises(ValueError, match="ingress observation"):
        _provenance_report(
            (
                replace(
                    operation,
                    ingress_observations=(
                        *operation.ingress_observations,
                        IngressObservation("request-2", utc(3), "same_key_replay"),
                    ),
                ),
            ),
            (ingress,),
            scope,
        )


def test_historical_report_rejects_ingress_observations_without_ingress_evidence() -> (
    None
):
    from app.services.operation_insights.contracts import (
        AuthorizedOwnershipEpoch,
        IngressObservation,
    )

    scope = Scope(
        frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch("wallet-1", "epoch-A", utc(1), utc(8)),
        ),
    )
    operation = Operation(
        "operation-1",
        "wallet-1",
        "first_observed_evidence",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="anchor-A",
        ingress_observations=(
            IngressObservation("request-1", utc(2), "execution_intent"),
        ),
    )

    with pytest.raises(ValueError, match="historical time_basis"):
        _provenance_report((operation,), (), scope, "first_observed_evidence")


def test_window_ingress_is_separate_from_inspector_roots() -> None:
    ingress = Evidence(
        "ingress_event",
        "event-1",
        "wallet-1",
        request_id="request-1",
        occurred_at=utc(2),
        event_kind="ingress",
        request_disposition="execution_intent",
        ownership_epoch_id="epoch-A",
        original_operation_anchor_id="old-anchor",
    )
    batch = EvidenceBatch(
        (),
        Snapshot(utc(8), "snapshot-1", True, None),
        Coverage(sources=()),
        window_ingress=(ingress,),
    )

    assert batch.rows == ()
    assert batch.window_ingress == (ingress,)
    for invalid in (
        replace(ingress, event_kind="terminal"),
        replace(ingress, wallet_id=None),
        replace(ingress, ownership_epoch_id=None),
        replace(ingress, original_operation_anchor_id=None),
        replace(ingress, request_id=None),
        replace(ingress, occurred_at=None),
        replace(ingress, request_disposition=None),
    ):
        with pytest.raises(ValueError, match="window_ingress"):
            replace(batch, window_ingress=(invalid,))
    with pytest.raises(ValidationError, match="window_ingress"):
        replace(batch, window_ingress=[ingress])  # type: ignore[arg-type]


def test_unknown_wallet_never_maps_to_an_account() -> None:
    mapping = AccountMapping(
        version="v1",
        intervals=(MappingInterval("wallet-1", "account-1", "eligible", utc(1), None),),
    )

    result = attribute(None, utc(4), mapping)

    assert result.account_id is None
    assert result.account_class == "unknown"
    assert result.mapping_status == "wallet_unknown"


def test_walletless_operation_defaults_to_unknown_and_rejects_account_attribution() -> (
    None
):
    operation = Operation("operation-1", None, "ingress")

    assert operation.account_id is None
    assert operation.account_class == "unknown"
    assert operation.mapping_status == "wallet_unknown"
    with pytest.raises(ValueError, match="wallet_unknown"):
        Operation("operation-2", None, "ingress", account_id="account-1")


def test_scope_rejects_walletless_wildcard() -> None:
    with pytest.raises(ValidationError, match="wallet_ids"):
        Scope(wallet_ids=frozenset({None}))  # type: ignore[arg-type]


def test_unknown_wallet_count_permission_does_not_expand_wallet_scope() -> None:
    default = Scope(wallet_ids=frozenset({"wallet-1"}))
    aggregate_only = Scope(wallet_ids=frozenset(), allow_unknown_wallet_counts=True)

    assert default.allow_unknown_wallet_counts is False
    assert aggregate_only.allow_unknown_wallet_counts is True
    assert aggregate_only.wallet_ids == frozenset()
    assert default.authorized_ownership_epochs == ()
    assert aggregate_only.authorized_ownership_epochs == ()
    with pytest.raises(ValidationError, match="allow_unknown_wallet_counts"):
        Scope(frozenset({"wallet-1"}), allow_unknown_wallet_counts="yes")  # type: ignore[arg-type]


def test_scope_carries_only_explicit_bounded_ownership_epochs() -> None:
    from app.services.operation_insights.contracts import AuthorizedOwnershipEpoch

    epoch = AuthorizedOwnershipEpoch("wallet-1", "epoch-1", utc(1), utc(5))
    scope = Scope(
        wallet_ids=frozenset({"wallet-1"}), authorized_ownership_epochs=(epoch,)
    )

    assert scope.authorized_ownership_epochs == (epoch,)
    assert asdict(epoch)["evidence_until"] == utc(5)
    with pytest.raises(ValueError, match="evidence_until"):
        AuthorizedOwnershipEpoch("wallet-1", "epoch-2", utc(5), utc(5))
    with pytest.raises(ValueError, match="UTC"):
        AuthorizedOwnershipEpoch("wallet-1", "epoch-2", datetime(2026, 10, 1), utc(5))
    with pytest.raises(ValueError, match="wallet"):
        Scope(
            wallet_ids=frozenset({"wallet-1"}),
            authorized_ownership_epochs=(
                AuthorizedOwnershipEpoch("wallet-2", "epoch-2", utc(1), utc(5)),
            ),
        )
    with pytest.raises(ValidationError, match="authorized_ownership_epochs"):
        Scope(
            wallet_ids=frozenset({"wallet-1"}),
            authorized_ownership_epochs=[epoch],
        )  # type: ignore[arg-type]


def test_unknown_wallet_aggregate_uses_fixed_complete_day_buckets() -> None:
    from app.services.operation_insights.contracts import UnknownWalletCount

    seven_days = UnknownWalletCount("complete", 0, utc(1), utc(8))
    thirty_days = UnknownWalletCount("complete", 3, utc(1), utc(31))

    assert seven_days.count == 0
    assert thirty_days.count == 3
    assert UnknownWalletCount("unavailable").count is None
    assert UnknownWalletCount("partial").count is None
    with pytest.raises(ValueError, match="bucket"):
        UnknownWalletCount("complete", 0, utc(1), utc(2))
    with pytest.raises(ValueError, match="bucket"):
        UnknownWalletCount(
            "complete", 0, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), utc(8)
        )


@pytest.mark.parametrize("status", ["not_authorized", "unavailable", "partial"])
def test_incomplete_unknown_wallet_aggregate_cannot_claim_zero(status: str) -> None:
    from app.services.operation_insights.contracts import UnknownWalletCount

    with pytest.raises(ValueError, match="count"):
        UnknownWalletCount(status, 0)


def test_complete_unknown_wallet_aggregate_requires_count_and_day_end() -> None:
    from app.services.operation_insights.contracts import UnknownWalletCount

    with pytest.raises(ValueError, match="count"):
        UnknownWalletCount("complete", None, utc(1), utc(8))

    aggregate = UnknownWalletCount("complete", 0, utc(1), utc(8))
    scope = Scope(frozenset(), allow_unknown_wallet_counts=True)
    report = Report(
        report_id="report-1",
        generated_at=utc(8),
        as_of=utc(8),
        snapshot_cutoff=utc(8),
        window_start=utc(1),
        window_end=utc(8),
        time_basis="ingress",
        environment=None,
        source_release=None,
        coverage=Coverage(sources=()),
        mapping_version="v1",
        exclusions=(),
        operations=(),
        evidence=(),
        metrics=(),
        unknown_wallet_aggregate=aggregate,
        authorized_scope=scope,
    )
    midday = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    shifted = replace(
        report,
        as_of=midday,
        window_start=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        window_end=midday,
        authorized_scope=scope,
    )

    assert asdict(report)["unknown_wallet_aggregate"]["count"] == 0
    assert shifted.unknown_wallet_aggregate == report.unknown_wallet_aggregate
    with pytest.raises(ValueError, match="bucket_end"):
        replace(report, as_of=utc(9), window_end=utc(9), authorized_scope=scope)
    with pytest.raises(ValueError, match="window"):
        replace(
            report,
            as_of=utc(31),
            window_start=utc(24),
            window_end=utc(31),
            snapshot_cutoff=utc(31),
            unknown_wallet_aggregate=UnknownWalletCount("complete", 3, utc(1), utc(31)),
            authorized_scope=scope,
        )
    with pytest.raises(ValueError, match="snapshot_cutoff"):
        replace(report, snapshot_cutoff=utc(7), authorized_scope=scope)


def test_report_requires_scope_even_without_raw_rows_or_unknown_aggregate() -> None:
    with pytest.raises(ValueError, match="authorized_scope"):
        _provenance_report((), (), None)


def test_unknown_wallet_aggregate_requires_permission_and_matching_window() -> None:
    from app.services.operation_insights.contracts import UnknownWalletCount

    base = _provenance_report((), (), Scope(frozenset()))
    permitted = Scope(frozenset(), allow_unknown_wallet_counts=True)
    for status in ("complete", "partial"):
        aggregate = UnknownWalletCount(
            status, 0 if status == "complete" else None, utc(1), utc(8)
        )
        with pytest.raises(ValueError, match="allow_unknown_wallet_counts"):
            replace(
                base,
                unknown_wallet_aggregate=aggregate,
                authorized_scope=Scope(frozenset()),
            )
        assert replace(
            base, unknown_wallet_aggregate=aggregate, authorized_scope=permitted
        )

    with pytest.raises(ValueError, match="window"):
        replace(
            base,
            as_of=utc(31),
            window_start=utc(24),
            window_end=utc(31),
            snapshot_cutoff=utc(31),
            unknown_wallet_aggregate=UnknownWalletCount(
                "partial", None, utc(1), utc(31)
            ),
            authorized_scope=permitted,
        )
    with pytest.raises(ValueError, match="authorized_scope"):
        replace(
            base,
            unknown_wallet_aggregate=UnknownWalletCount("complete", 0, utc(1), utc(8)),
        )


def test_typed_authority_and_replay_facts_preserve_observed_states() -> None:
    facts = EvidenceStateFacts(
        permit_status="revoked",
        permit_expires_at=utc(2),
        permit_revoked_at=utc(3),
        approval_status="expired",
        approval_expires_at=utc(2),
        approval_decided_at=utc(3),
        permit_request_status="rejected",
        idempotency_outcome="payload_mismatch",
        ledger_action="refund",
    )

    assert facts.permit_status == "revoked"
    assert facts.permit_revoked_at == utc(3)
    assert facts.approval_status == "expired"
    assert facts.approval_decided_at == utc(3)
    assert facts.permit_request_status == "rejected"
    assert facts.idempotency_outcome == "payload_mismatch"
    assert facts.ledger_action == "refund"
    assert EvidenceStateFacts().idempotency_outcome == "unknown"


def test_authority_facts_reject_unbounded_state_and_naive_time() -> None:
    with pytest.raises(ValidationError, match="permit_status"):
        EvidenceStateFacts(permit_status="raw error text")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="permit_expires_at"):
        EvidenceStateFacts(permit_expires_at=datetime(2026, 10, 2))


def test_multiple_dispatch_checkpoints_survive_one_evidence_row() -> None:
    evidence = Evidence(
        "dispatch",
        "attempt-1",
        "wallet-1",
        stage_timestamps=(
            StageTimestamp("prepared", utc(1), "dispatch", "attempt-1"),
            StageTimestamp("dispatch_claimed", utc(2), "dispatch", "attempt-1"),
        ),
    )

    assert [entry["stage"] for entry in asdict(evidence)["stage_timestamps"]] == [
        "prepared",
        "dispatch_claimed",
    ]


def test_report_rejects_mixed_operation_and_metric_time_bases() -> None:
    common = dict(
        report_id="report-1",
        generated_at=utc(5),
        as_of=utc(5),
        snapshot_cutoff=utc(5),
        window_start=utc(1),
        window_end=utc(5),
        time_basis="ingress",
        environment=None,
        source_release=None,
        coverage=Coverage(sources=()),
        mapping_version="v1",
        exclusions=(),
        evidence=(),
    )
    operation = Operation("operation-1", "wallet-1", "first_observed_evidence")
    metric = Metric(
        "requests",
        1,
        1,
        1,
        1.0,
        "request",
        Window(utc(1), utc(5), "first_observed_evidence"),
        0,
        0,
        "complete",
    )

    with pytest.raises(ValueError, match="time_basis"):
        Report(**common, operations=(operation,), metrics=())
    with pytest.raises(ValueError, match="time_basis"):
        Report(**common, operations=(), metrics=(metric,))


def test_account_attribution_rejects_inconsistent_mapping_status() -> None:
    with pytest.raises(ValueError, match="mapped"):
        AccountAttribution(None, "eligible", "mapped")
    with pytest.raises(ValueError, match="mapped"):
        AccountAttribution("account-1", "unknown", "mapped")
    with pytest.raises(ValueError, match="unmapped"):
        AccountAttribution("account-1", "eligible", "unmapped")


def test_operation_rejects_inconsistent_wallet_and_account_attribution() -> None:
    with pytest.raises(ValueError, match="unmapped"):
        Operation("operation-1", "wallet-1", "ingress", account_class="eligible")
    with pytest.raises(ValueError, match="wallet_unknown"):
        Operation("operation-2", "wallet-1", "ingress", mapping_status="wallet_unknown")
    mapped = Operation(
        "operation-3",
        "wallet-1",
        "ingress",
        account_id="account-1",
        account_class="eligible",
        mapping_status="mapped",
    )

    assert mapped.account_id == "account-1"


def test_report_cohort_endpoint_equals_as_of() -> None:
    with pytest.raises(ValueError, match="as_of"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(4),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=Coverage(sources=()),
            mapping_version="v1",
            exclusions=(),
            operations=(),
            evidence=(),
            metrics=(),
        )


def test_refund_evidence_keeps_link_and_amount_checks_independent() -> None:
    evidence = Evidence(
        "ledger",
        "entry-1",
        "wallet-1",
        state_facts=EvidenceStateFacts(
            ledger_action="refund",
            ledger_link_verified=False,
            refund_amount_matches_debit=None,
        ),
    )

    facts = asdict(evidence)["state_facts"]
    assert facts["ledger_link_verified"] is False
    assert facts["refund_amount_matches_debit"] is None
    assert facts["refund_state"] is None
    verified = EvidenceStateFacts(
        ledger_link_verified=True, refund_amount_matches_debit=True
    )
    unknown = EvidenceStateFacts()
    assert verified.ledger_link_verified is True
    assert verified.refund_amount_matches_debit is True
    assert unknown.ledger_link_verified is None
    assert unknown.refund_amount_matches_debit is None
    with pytest.raises(ValidationError, match="refund_amount_matches_debit"):
        EvidenceStateFacts(refund_amount_matches_debit="yes")  # type: ignore[arg-type]


def test_historical_evidence_does_not_infer_ingress_or_attempts() -> None:
    historical = Evidence(
        "idempotency",
        "record-1",
        "wallet-1",
        state_facts=EvidenceStateFacts(idempotency_outcome="replayed"),
    )

    assert historical.event_kind is None
    assert historical.request_disposition is None
    assert historical.request_id is None
    assert historical.attempt_id is None


def test_synthetic_ingress_event_round_trips_with_bounded_safe_fields() -> None:
    event = Evidence(
        source="insight_event",
        source_id="event-1",
        wallet_id=None,
        event_kind="ingress",
        request_disposition="unknown",
        request_id="request-1",
        occurred_at=utc(1),
    )

    wire = json.loads(json.dumps(asdict(event), default=str))

    assert wire["event_kind"] == "ingress"
    assert wire["request_disposition"] == "unknown"
    assert wire["request_id"] == "request-1"
    assert wire["attempt_id"] is None
    assert wire["wallet_id"] is None
    assert (
        not {"api_key", "key_hash", "payload", "tool_arguments", "raw_error"}
        & wire.keys()
    )


@pytest.mark.parametrize("event_kind", ["ingress", "terminal", "attempt"])
def test_evidence_accepts_observed_event_kinds(event_kind: str) -> None:
    evidence = Evidence("insight_event", "event-1", "wallet-1", event_kind=event_kind)

    assert evidence.event_kind == event_kind


@pytest.mark.parametrize(
    "disposition",
    [
        "execution_intent",
        "same_key_replay",
        "status_read",
        "non_execution_read",
        "unknown",
    ],
)
def test_evidence_accepts_observed_request_dispositions(disposition: str) -> None:
    evidence = Evidence(
        "insight_event", "event-1", "wallet-1", request_disposition=disposition
    )

    assert evidence.request_disposition == disposition


@pytest.mark.parametrize("invalid", ["replay", 1])
def test_evidence_rejects_invalid_event_kind(invalid: object) -> None:
    with pytest.raises(ValidationError, match="event_kind"):
        Evidence("insight_event", "event-1", "wallet-1", event_kind=invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", ["read", 1])
def test_evidence_rejects_invalid_request_disposition(invalid: object) -> None:
    with pytest.raises(ValidationError, match="request_disposition"):
        Evidence("insight_event", "event-1", "wallet-1", request_disposition=invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "disposition", ["same_key_replay", "status_read", "non_execution_read"]
)
def test_attempt_event_rejects_nonexecution_disposition(disposition: str) -> None:
    with pytest.raises(ValueError, match="attempt"):
        Evidence(
            "insight_event",
            "event-1",
            "wallet-1",
            event_kind="attempt",
            request_disposition=disposition,
        )


def test_report_does_not_mix_ingress_and_historical_operations() -> None:
    ingress = Operation("ingress-1", "wallet-1", "ingress")
    historical = Operation("historical-1", "wallet-1", "first_observed_evidence")

    with pytest.raises(ValueError, match="time_basis"):
        Report(
            report_id="report-1",
            generated_at=utc(5),
            as_of=utc(5),
            snapshot_cutoff=utc(5),
            window_start=utc(1),
            window_end=utc(5),
            time_basis="ingress",
            environment=None,
            source_release=None,
            coverage=Coverage(sources=()),
            mapping_version="v1",
            exclusions=(),
            operations=(ingress, historical),
            evidence=(
                Evidence("insight_event", "event-1", "wallet-1", event_kind="ingress"),
                Evidence("audit", "audit-1", "wallet-1"),
            ),
            metrics=(),
        )
