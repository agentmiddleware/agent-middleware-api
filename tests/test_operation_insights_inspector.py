"""Evidence-only inspector regressions for the approved incident matrix."""

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.operation_insights.contracts import (
    AccountMapping,
    Coverage,
    Evidence,
    EvidenceBatch,
    EvidenceRef,
    EvidenceStateFacts,
    MappingInterval,
    Snapshot,
    StageTimestamp,
)
from app.services.operation_insights.inspect import inspect_operations


BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)
MAPPING = AccountMapping(
    "mapping-1", (MappingInterval("wallet-1", "account-1", "eligible", BASE, None),)
)
INCIDENTS = json.loads(
    (Path(__file__).parent / "fixtures/operation_insights/incidents.json").read_text()
)


def at(hour: int) -> datetime:
    return BASE + timedelta(hours=hour)


def row(
    source: str,
    source_id: str,
    *,
    hour: int | None = None,
    wallet: str = "wallet-1",
    epoch: str = "epoch-1",
    anchor: str = "anchor-1",
    tool: str | None = "tool-1",
    **kwargs: object,
) -> Evidence:
    return Evidence(
        source,
        source_id,
        wallet,
        tool=tool,
        occurred_at=at(hour) if hour is not None else None,
        ownership_epoch_id=epoch,
        original_operation_anchor_id=anchor,
        **kwargs,
    )


def batch(*rows: Evidence, coverage: Coverage | None = None) -> EvidenceBatch:
    return EvidenceBatch(
        rows,
        Snapshot(at(100), "snapshot-1", True, None),
        coverage or Coverage(sources=()),
    )


@pytest.mark.parametrize("incident", INCIDENTS, ids=lambda item: item["name"])
def test_incident_matrix(incident: dict[str, object]) -> None:
    evidence = tuple(
        row(
            item["source"],
            item["id"],
            hour=item["at"],
            state_facts=EvidenceStateFacts(**item["facts"]),
            reason_code=item.get("reason"),
        )
        for item in incident["rows"]
    )

    result = inspect_operations(batch(*evidence), MAPPING)

    assert len(result) == 1
    operation = result[0]
    expected = incident["expected"]
    for field in (
        "gateway_outcome",
        "effect_state",
        "refund_state",
        "budget_release_state",
        "failure_class",
        "next_action",
    ):
        assert getattr(operation, field) == expected[field]
    assert len(operation.attempt_ids) == expected["attempts"]
    assert operation.unresolved_since == min(item.occurred_at for item in evidence)
    assert len(operation.evidence_refs) == len(evidence)
    assert all(ref.wallet_id == "wallet-1" for ref in operation.evidence_refs)


def test_incident_matrix_lost_ack_remains_unresolved_with_proven_effect() -> None:
    incident = next(
        item for item in INCIDENTS if item["name"] == "lost_ack_after_effect"
    )
    evidence = tuple(
        row(
            item["source"],
            item["id"],
            hour=item["at"],
            state_facts=EvidenceStateFacts(**item["facts"]),
        )
        for item in incident["rows"]
    )

    operation = inspect_operations(batch(*evidence), MAPPING)[0]

    assert operation.effect_state == "confirmed"
    assert operation.gateway_outcome == "unknown"
    assert operation.unresolved_since == at(4)
    assert operation.next_action == "manual_review"


def test_correlation_boundaries_count_only_ingress_and_trusted_attempts() -> None:
    ingress = row(
        "insight_event",
        "event-1",
        hour=1,
        request_id="request-1",
        event_kind="ingress",
        request_disposition="execution_intent",
    )
    replay = row(
        "insight_event",
        "event-2",
        hour=2,
        request_id="request-2",
        event_kind="ingress",
        request_disposition="same_key_replay",
    )
    status = row(
        "insight_event",
        "event-3",
        hour=3,
        request_id="request-3",
        event_kind="ingress",
        request_disposition="status_read",
    )
    historical_audit = row(
        "audit",
        "audit-1",
        hour=4,
        request_id="request-4",
        attempt_id="untrusted-attempt",
    )
    attempt_a = row(
        "insight_event", "event-4", hour=5, attempt_id="attempt-1", event_kind="attempt"
    )
    attempt_b = row("dispatch", "attempt-2", hour=6, attempt_id="attempt-2")

    operation = inspect_operations(
        batch(ingress, replay, status, historical_audit, attempt_a, attempt_b), MAPPING
    )[0]

    assert operation.request_ids == ("request-1", "request-2", "request-3")
    assert operation.attempt_ids == ("attempt-1", "attempt-2")
    assert operation.execution_intent is True
    assert operation.replay_only is False
    assert [
        asdict(observation)["disposition"]
        for observation in operation.ingress_observations
    ] == ["execution_intent", "same_key_replay", "status_read"]


def test_distinct_original_anchors_and_wallet_epochs_never_merge_by_request_or_time() -> (
    None
):
    rows = (
        row("audit", "audit-1", hour=1, request_id="same-request"),
        row("audit", "audit-2", hour=1, request_id="same-request", anchor="anchor-2"),
        row("audit", "audit-3", hour=1, request_id="same-request", epoch="epoch-2"),
        row("audit", "audit-4", hour=1, request_id="same-request", wallet="wallet-2"),
        row("audit", "audit-5", hour=1, request_id="same-request", tool="tool-2"),
    )

    operations = inspect_operations(batch(*rows), MAPPING)

    assert len(operations) == 4
    assert all(operation.request_ids == () for operation in operations)
    assert {operation.wallet_id for operation in operations} == {"wallet-1", "wallet-2"}
    conflicted = next(
        operation
        for operation in operations
        if operation.wallet_id == "wallet-1"
        and operation.ownership_epoch_id == "epoch-1"
        and operation.original_operation_anchor_id == "anchor-1"
    )
    assert conflicted.tool is None
    assert "tool_mismatch" in conflicted.conflicts


def test_conflicting_or_dangling_edges_never_widen_evidence_scope() -> None:
    foreign_ref = EvidenceRef("audit", "foreign", "wallet-2", "epoch-2", "anchor-2")
    dangling_ref = EvidenceRef("audit", "missing", "wallet-1", "epoch-1", "anchor-1")
    root = row("dispatch", "attempt-1", hour=1, edges=(foreign_ref, dangling_ref))
    other = row(
        "audit",
        "foreign",
        hour=2,
        wallet="wallet-2",
        epoch="epoch-2",
        anchor="anchor-2",
    )

    operations = inspect_operations(batch(root, other), MAPPING)

    assert len(operations) == 2
    own = next(
        operation for operation in operations if operation.wallet_id == "wallet-1"
    )
    assert own.evidence_refs == (
        EvidenceRef("dispatch", "attempt-1", "wallet-1", "epoch-1", "anchor-1"),
    )
    assert "cross_scope_edge" in own.conflicts
    assert "dangling_edge" in own.evidence_gaps


def test_null_conflicting_and_late_timestamps_keep_evidence_and_skew_flags() -> None:
    unknown_time = row("audit", "audit-1", ingested_at=at(10))
    backwards = row(
        "dispatch",
        "attempt-1",
        hour=8,
        ingested_at=at(7),
        stage_timestamps=(
            StageTimestamp("prepared", at(9), "dispatch", "attempt-1"),
            StageTimestamp("dispatch_claimed", at(8), "dispatch", "attempt-1"),
        ),
    )

    operation = inspect_operations(batch(unknown_time, backwards), MAPPING)[0]

    assert len(operation.evidence_refs) == 2
    assert operation.first_seen_at == at(8)
    assert operation.last_seen_at == at(10)
    assert "occurrence_time_missing" in operation.evidence_gaps
    assert "ingestion_before_occurrence" in operation.conflicts
    assert "stage_time_order_conflict" in operation.conflicts
    assert operation.stage_timestamps[0].at == at(8)


def test_missing_receipt_and_deleted_recovery_do_not_prove_no_effect() -> None:
    dispatch = row(
        "dispatch",
        "attempt-1",
        hour=2,
        state_facts=EvidenceStateFacts(dispatch_state="dispatch_claimed"),
    )
    coverage = Coverage(
        sources=(), gaps=("receipt_retention_unknown", "recovery_record_deleted")
    )

    operation = inspect_operations(batch(dispatch, coverage=coverage), MAPPING)[0]

    assert operation.effect_state == "unknown"
    assert operation.gateway_outcome == "unknown"
    assert "receipt_missing" in operation.evidence_gaps
    assert "recovery_record_deleted" in operation.evidence_gaps
    assert operation.next_action == "manual_review"


def test_refund_claim_needs_verified_link_and_matching_amount() -> None:
    claim = row(
        "dispatch",
        "attempt-1",
        hour=2,
        state_facts=EvidenceStateFacts(refund_state="completed"),
    )
    mismatch = row(
        "ledger",
        "refund-1",
        hour=3,
        state_facts=EvidenceStateFacts(
            ledger_action="refund",
            ledger_link_verified=True,
            refund_amount_matches_debit=False,
        ),
    )

    operation = inspect_operations(batch(claim, mismatch), MAPPING)[0]

    assert operation.refund_state == "conflicting"
    assert operation.effect_state == "unknown"
    assert "refund_evidence_conflict" in operation.conflicts
    assert operation.next_action == "manual_review"


def test_expected_denial_and_unknown_reason_remain_distinct() -> None:
    denial = row(
        "audit",
        "audit-1",
        hour=2,
        reason_code="policy_denied",
        state_facts=EvidenceStateFacts(policy_decision="deny"),
    )
    unexplained = replace(
        denial,
        source_id="audit-2",
        original_operation_anchor_id="anchor-2",
        reason_code=None,
        state_facts=EvidenceStateFacts(),
    )

    operations = inspect_operations(batch(denial, unexplained), MAPPING)

    expected = next(
        operation
        for operation in operations
        if operation.original_operation_anchor_id == "anchor-1"
    )
    unknown = next(
        operation
        for operation in operations
        if operation.original_operation_anchor_id == "anchor-2"
    )
    assert expected.failure_class == "expected_denial"
    assert expected.observed_denial is True
    assert expected.reason_code == "policy_denied"
    assert unknown.failure_class == "unknown"
    assert unknown.observed_denial is None


def test_mapping_uses_ingress_occurrence_or_historical_first_observation() -> None:
    mapping = AccountMapping(
        "mapping-1",
        (
            MappingInterval("wallet-1", "old", "eligible", BASE, at(4)),
            MappingInterval("wallet-1", "new", "eligible", at(4), None),
        ),
    )
    ingress = row(
        "insight_event",
        "event-1",
        hour=2,
        request_id="request-1",
        event_kind="ingress",
        request_disposition="execution_intent",
    )
    terminal = row(
        "receipt",
        "receipt-1",
        hour=6,
        state_facts=EvidenceStateFacts(gateway_outcome="succeeded"),
    )
    historical = replace(
        terminal, source_id="receipt-2", original_operation_anchor_id="anchor-2"
    )

    operations = inspect_operations(batch(ingress, terminal, historical), mapping)

    earlier = next(
        operation
        for operation in operations
        if operation.original_operation_anchor_id == "anchor-1"
    )
    later = next(
        operation
        for operation in operations
        if operation.original_operation_anchor_id == "anchor-2"
    )
    assert earlier.time_basis == "ingress"
    assert earlier.first_seen_at == at(2)
    assert earlier.account_id == "old"
    assert later.time_basis == "first_observed_evidence"
    assert later.account_id == "new"


def test_partial_coverage_cannot_turn_absence_into_success() -> None:
    evidence = row("idempotency", "record-1", hour=2)
    coverage = Coverage(sources=(), truncated=True, gaps=("audit_unavailable",))

    operation = inspect_operations(batch(evidence, coverage=coverage), MAPPING)[0]

    assert operation.gateway_outcome == "unknown"
    assert operation.effect_state == "unknown"
    assert "audit_unavailable" in operation.evidence_gaps
    assert operation.failure_class == "unknown"


def test_unknown_tool_evidence_uses_the_one_verified_tool_independent_of_order() -> (
    None
):
    permit = row("permit", "permit-1", hour=1, tool=None)
    dispatch = row("dispatch", "attempt-1", hour=2, tool="tool-1")

    forward = inspect_operations(batch(permit, dispatch), MAPPING)[0]
    reverse = inspect_operations(batch(dispatch, permit), MAPPING)[0]

    assert forward.tool == "tool-1"
    assert reverse.operation_id == forward.operation_id


def test_heuristic_request_match_marks_separate_operations_ambiguous() -> None:
    first = row("audit", "audit-1", hour=1, request_id="shared-request")
    second = row(
        "audit", "audit-2", hour=2, anchor="anchor-2", request_id="shared-request"
    )

    operations = inspect_operations(batch(first, second), MAPPING)

    assert len(operations) == 2
    assert all(item.correlation_status == "ambiguous" for item in operations)
    assert all(
        "heuristic_correlation_candidate" in item.evidence_gaps for item in operations
    )


def test_unscoped_provenance_is_rejected_before_inspection() -> None:
    evidence = row("audit", "audit-1", hour=1, wallet=None)

    with pytest.raises(ValueError, match="authorized wallet"):
        inspect_operations(batch(evidence), MAPPING)


def test_late_tool_identification_keeps_original_operation_id() -> None:
    permit = row("permit", "permit-1", hour=1, tool=None)
    dispatch = row("dispatch", "attempt-1", hour=2, tool="tool-1")

    initial = inspect_operations(batch(permit), MAPPING)[0]
    revised = inspect_operations(batch(permit, dispatch), MAPPING)[0]

    assert revised.operation_id == initial.operation_id


def test_conflicting_tools_remain_one_original_operation_with_all_evidence() -> None:
    rows = (
        row("permit", "permit-1", hour=1, tool=None),
        row("audit", "audit-1", hour=2, tool=None),
        row("dispatch", "attempt-1", hour=3, tool="tool-1"),
        row("dispatch", "attempt-2", hour=4, tool="tool-2"),
    )

    operations = inspect_operations(batch(*rows), MAPPING)

    assert len(operations) == 1
    assert operations[0].tool is None
    assert len(operations[0].evidence_refs) == 4
    assert "tool_mismatch" in operations[0].conflicts
    assert operations[0].next_action == "manual_review"


def test_payload_mismatch_fact_classifies_an_expected_denial() -> None:
    mismatch = row(
        "idempotency",
        "record-1",
        hour=2,
        state_facts=EvidenceStateFacts(idempotency_outcome="payload_mismatch"),
    )

    operation = inspect_operations(batch(mismatch), MAPPING)[0]

    assert operation.failure_class == "expected_denial"
    assert operation.observed_denial is True


def test_late_ingestion_preserves_occurrence_timeline_and_discloses_arrival_order() -> (
    None
):
    first = row("audit", "audit-1", hour=1, ingested_at=at(5))
    second = row("dispatch", "attempt-1", hour=2, ingested_at=at(3))

    operation = inspect_operations(batch(second, first), MAPPING)[0]

    assert operation.first_seen_at == at(1)
    assert [point.source_id for point in operation.stage_timestamps] == [
        "audit-1",
        "attempt-1",
    ]
    assert "ingestion_order_differs" in operation.evidence_gaps


@pytest.mark.parametrize(
    "reason",
    ["idempotency_key_blank", "idempotency_key_conflict", "invalid_idempotency_key"],
)
def test_preexecution_validation_reason_is_an_expected_denial(reason: str) -> None:
    validation = row("audit", "audit-1", hour=1, reason_code=reason)

    operation = inspect_operations(batch(validation), MAPPING)[0]

    assert operation.failure_class == "expected_denial"
    assert operation.failure_stage == "validation"


def test_terminal_gateway_receipt_resolves_an_earlier_dispatch_claim() -> None:
    claim = row(
        "dispatch",
        "attempt-1",
        hour=2,
        state_facts=EvidenceStateFacts(dispatch_state="dispatch_claimed"),
    )
    receipt = row(
        "receipt",
        "receipt-1",
        hour=3,
        state_facts=EvidenceStateFacts(gateway_outcome="succeeded"),
    )

    operation = inspect_operations(batch(claim, receipt), MAPPING)[0]

    assert operation.gateway_outcome == "succeeded"
    assert operation.effect_state == "unknown"
    assert operation.next_action == "inspect"


def test_unreferenced_stage_timestamp_is_flagged_without_dropping_operation() -> None:
    evidence = row(
        "dispatch",
        "attempt-1",
        hour=2,
        stage_timestamps=(StageTimestamp("prepared", at(1), "dispatch", "missing"),),
    )

    operation = inspect_operations(batch(evidence), MAPPING)[0]

    assert len(operation.evidence_refs) == 1
    assert len(operation.stage_timestamps) == 1
    assert operation.stage_timestamps[0].source_id == "attempt-1"
    assert "stage_timestamp_unreferenced" in operation.evidence_gaps


def test_ingress_cohort_anchors_on_first_execution_intent_not_earlier_reads() -> None:
    status = row(
        "insight_event",
        "status-1",
        hour=1,
        event_kind="ingress",
        request_id="request-status",
        request_disposition="status_read",
    )
    replay = row(
        "insight_event",
        "replay-1",
        hour=2,
        event_kind="ingress",
        request_id="request-replay",
        request_disposition="same_key_replay",
    )
    intent = row(
        "insight_event",
        "intent-1",
        hour=3,
        event_kind="ingress",
        request_id="request-intent",
        request_disposition="execution_intent",
    )

    operation = inspect_operations(batch(status, replay, intent), MAPPING)[0]

    assert operation.time_basis == "ingress"
    assert operation.first_seen_at == at(3)
    assert operation.unresolved_since == at(1)
    assert operation.request_ids == (
        "request-intent",
        "request-replay",
        "request-status",
    )


def test_replay_only_root_has_no_execution_intent_cohort_anchor() -> None:
    replay = row(
        "insight_event",
        "replay-1",
        hour=2,
        event_kind="ingress",
        request_id="request-replay",
        request_disposition="same_key_replay",
        stage_timestamps=(
            StageTimestamp("request_observed", at(1), "insight_event", "replay-1"),
        ),
    )

    operation = inspect_operations(batch(replay), MAPPING)[0]

    assert operation.first_seen_at is None
    assert operation.execution_intent is False
    assert operation.replay_only is True
    assert operation.unresolved_since == at(1)
    assert "execution_intent_ingress_missing" in operation.evidence_gaps


def test_historical_first_observation_includes_verified_stage_checkpoint() -> None:
    dispatch = row(
        "dispatch",
        "attempt-1",
        hour=6,
        stage_timestamps=(StageTimestamp("prepared", at(2), "dispatch", "attempt-1"),),
    )

    operation = inspect_operations(batch(dispatch), MAPPING)[0]

    assert operation.time_basis == "first_observed_evidence"
    assert operation.first_seen_at == at(2)
    assert operation.last_seen_at == at(6)


def test_ingress_without_request_identity_cannot_be_a_cohort_anchor() -> None:
    incomplete = row(
        "insight_event",
        "event-1",
        hour=2,
        event_kind="ingress",
        request_disposition="execution_intent",
    )

    operation = inspect_operations(batch(incomplete), MAPPING)[0]

    assert operation.time_basis == "ingress"
    assert operation.first_seen_at is None
    assert operation.execution_intent is None
    assert "ingress_identity_missing" in operation.evidence_gaps
