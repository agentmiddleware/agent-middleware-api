"""Offline account attribution and contract boundaries for operation insights."""

from dataclasses import FrozenInstanceError, asdict
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
    )

    assert asdict(report)["window_start"] == utc(1)
    assert asdict(report)["time_basis"] == "first_observed_evidence"
    assert report.schema_version == 1
    assert report.classification_version == 1


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
        operations=(operation,),
        evidence=(evidence,),
        metrics=(),
    )

    serialized = asdict(report)
    assert serialized["operations"][0]["wallet_id"] is None
    assert serialized["operations"][0]["mapping_status"] == "wallet_unknown"
    assert serialized["evidence"][0]["wallet_id"] is None
    assert serialized["evidence"][0]["edges"][0]["wallet_id"] is None


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
