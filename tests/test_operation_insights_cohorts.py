"""Bounded cohort arithmetic over synthetic, already-scoped evidence."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from app.services.operation_insights.cohorts import compute_metrics
from app.services.operation_insights.contracts import (
    AccountMapping,
    Coverage,
    Evidence,
    MappingInterval,
    Operation,
    Snapshot,
    SourceCoverage,
    Window,
)


AS_OF = datetime(2026, 10, 10, tzinfo=timezone.utc)
EARLIEST = datetime(2026, 9, 1, tzinfo=timezone.utc)


def at(days_before: int, hour: int = 0) -> datetime:
    return AS_OF - timedelta(days=days_before) + timedelta(hours=hour)


def window(days: int = 7, basis: str = "ingress") -> Window:
    return Window(at(days), AS_OF, basis)  # type: ignore[arg-type]


def complete_coverage(earliest: datetime = EARLIEST) -> Coverage:
    return Coverage(
        (SourceCoverage("insight_event", "available", earliest, True),),
        enumeration_complete=True,
    )


def snapshot(cutoff: datetime | None = None) -> Snapshot:
    return Snapshot(cutoff or AS_OF + timedelta(days=1), "snapshot-1", True, None)


def mapping(*entries: tuple[str, str, str]) -> AccountMapping:
    return AccountMapping(
        "mapping-1",
        tuple(
            MappingInterval(wallet, account, kind, EARLIEST, None)
            for wallet, account, kind in entries
        ),
    )


def ingress(
    request_id: str,
    wallet: str,
    when: datetime,
    disposition: str = "execution_intent",
    *,
    source_id: str | None = None,
    ingested_at: datetime | None = None,
) -> Evidence:
    return Evidence(
        "insight_event",
        source_id or f"event-{request_id}",
        wallet,
        request_id=request_id,
        event_kind="ingress",
        request_disposition=disposition,  # type: ignore[arg-type]
        occurred_at=when,
        ingested_at=ingested_at,
        ownership_epoch_id=f"epoch-{wallet}",
        original_operation_anchor_id=f"anchor-{request_id}",
    )


def operation(
    number: int,
    wallet: str,
    when: datetime,
    *,
    failure: str = "none",
    reason: str | None = None,
    logical: str | None = None,
    basis: str = "ingress",
    **values: object,
) -> Operation:
    return Operation(
        f"operation-{number}",
        wallet,
        basis,  # type: ignore[arg-type]
        first_seen_at=when,
        logical_operation_id=logical or f"logical-{number}",
        correlation_status="explicit",
        execution_intent=True if basis == "ingress" else None,
        reason_code=reason,
        failure_class=failure,  # type: ignore[arg-type]
        observed_fault=failure == "unexpected_fault",
        observed_denial=failure == "expected_denial",
        ownership_epoch_id=f"epoch-{wallet}",
        original_operation_anchor_id=f"anchor-{number}",
        **values,
    )


def calculate(
    current: tuple[Operation, ...],
    prior: tuple[Operation, ...],
    current_ingress: tuple[Evidence, ...],
    prior_ingress: tuple[Evidence, ...],
    account_mapping: AccountMapping,
    *,
    selected_window: Window | None = None,
    read_snapshot: Snapshot | None = None,
    coverage: Coverage | None = None,
    prior_coverage: Coverage | None = None,
):
    return compute_metrics(
        current,
        prior,
        current_ingress,
        prior_ingress,
        account_mapping,
        selected_window or window(),
        read_snapshot or snapshot(),
        coverage or complete_coverage(),
        prior_coverage or complete_coverage(),
    )


def test_counts_and_denominators() -> None:
    account_mapping = mapping(
        ("wa", "A", "eligible"),
        ("wb", "B", "eligible"),
        ("wc", "C", "eligible"),
        ("wd", "D", "eligible"),
        ("w-internal", "internal-1", "internal"),
        ("w-demo", "echo-demo", "demo"),
        ("w-ci", "ci-1", "CI"),
        ("w-monitor", "monitor-1", "monitoring"),
    )
    current = tuple(
        operation(
            number,
            ("wa", "wb", "wc")[number % 3],
            at(6),
            failure=(
                "unexpected_fault"
                if number < 2
                else "expected_denial"
                if number < 5
                else "unknown"
                if number < 7
                else "none"
            ),
            reason=f"reason_{number % 2}",
            tool="upstream.tool",
            attempt_ids=(f"attempt-{number}",),
            gateway_outcome="denied" if 2 <= number < 5 else "unknown",
        )
        for number in range(10)
    )
    current_ingress = tuple(
        ingress(f"request-{number}", ("wa", "wb", "wc")[number % 3], at(6))
        for number in range(10)
    ) + tuple(
        ingress(f"excluded-{kind}", wallet, at(5))
        for kind, wallet in (
            ("internal", "w-internal"),
            ("demo", "w-demo"),
            ("ci", "w-ci"),
            ("monitor", "w-monitor"),
            ("unknown", "w-unmapped"),
        )
    )
    prior_ingress = tuple(
        ingress(f"prior-{wallet}", wallet, at(9)) for wallet in ("wb", "wc", "wd")
    )

    result = calculate(current, (), current_ingress, prior_ingress, account_mapping)
    metrics = {m.name: m for m in result}
    zero_result = calculate((), (), (), (), account_mapping)
    zero_metrics = {m.name: m for m in zero_result}

    assert metrics["active_accounts"].count == 3
    assert metrics["returning_accounts"].numerator == 2
    assert metrics["returning_accounts"].denominator == 3
    assert metrics["returning_accounts"].ratio == 2 / 3
    assert metrics["fault_incidence"].numerator == 2
    assert metrics["fault_incidence"].denominator == 10
    assert metrics["gateway_completed_accounts"].count == 3
    assert metrics["gateway_succeeded_accounts"].count == 0
    assert metrics["denial_incidence"].numerator == 3
    assert metrics["denial_incidence"].denominator == 10
    assert metrics["fault_incidence"].unknown_count == 2
    assert metrics["attempts"].count == 10
    assert metrics["ambiguous_attempt_operations"].count == 0
    assert metrics["requests"].count == 15
    assert metrics["unknown_wallet_attributions"].count == 1
    assert metrics["excluded_demo_accounts"].count == 1
    assert metrics["excluded_internal_accounts"].count == 1
    assert metrics["excluded_CI_accounts"].count == 1
    assert metrics["excluded_monitoring_accounts"].count == 1
    assert zero_metrics["fault_incidence"].ratio is None


def test_exact_windows_and_revisions() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    start = at(7)
    end = AS_OF
    current = tuple(
        operation(number, "wa", start, reason="reason_a") for number in range(10001)
    ) + (
        operation(10001, "wa", end, reason="outside_end"),
        operation(
            10002, "wa", start - timedelta(microseconds=1), reason="before_start"
        ),
    )
    current_ingress = (
        ingress("at-start", "wa", start),
        ingress("at-end", "wa", end),
    )

    result = calculate(current, (), current_ingress, (), account_mapping)
    metrics = {m.name: m for m in result}
    reason_counts = {
        name: metric.count
        for name, metric in metrics.items()
        if name.startswith("reason.")
    }

    assert sum(reason_counts.values()) == 10001
    assert metrics["logical_operations"].count == 10001
    assert metrics["requests"].count == 1
    assert metrics["fault_incidence"].numerator == 0
    revised = (
        replace(current[0], observed_fault=True, last_seen_at=at(-1)),
    ) + current[1:]
    revised_metrics = {
        metric.name: metric
        for metric in calculate(revised, (), current_ingress, (), account_mapping)
    }
    assert revised_metrics["fault_incidence"].numerator == 1
    assert revised_metrics["logical_operations"].count == 10001


def test_failed_gateway_terminal_still_counts_as_completion() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    metrics = {
        item.name: item
        for item in calculate(
            (operation(1, "wa", at(2), gateway_outcome="failed"),),
            (),
            (),
            (),
            account_mapping,
        )
    }

    assert metrics["gateway_completed_accounts"].count == 1
    assert metrics["gateway_succeeded_accounts"].count == 0


def test_late_ingestion_labels_original_cohort_revision() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    occurred = at(2)
    received = AS_OF + timedelta(hours=1)
    request = ingress("late", "wa", occurred, ingested_at=received)
    terminal = Evidence(
        "insight_event",
        "event-terminal",
        "wa",
        event_kind="terminal",
        occurred_at=occurred,
        ingested_at=received,
        ownership_epoch_id="epoch-wa",
        original_operation_anchor_id="anchor-1",
    )
    from app.services.operation_insights.contracts import EvidenceRef

    current = operation(
        1,
        "wa",
        occurred,
        last_seen_at=occurred,
        evidence_refs=(
            EvidenceRef(
                "insight_event", "event-terminal", "wa", "epoch-wa", "anchor-1"
            ),
        ),
    )
    metrics = {
        metric.name: metric
        for metric in compute_metrics(
            (current,),
            (),
            (request,),
            (),
            account_mapping,
            window(),
            snapshot(),
            complete_coverage(),
            complete_coverage(),
            current_evidence=(terminal,),
        )
    }
    assert metrics["requests"].count == 1
    assert metrics["post_window_ingress_events"].count == 1
    assert metrics["post_window_observed_updates"].count == 1
    assert metrics["eligible_operations"].count == 1


def test_late_duplicate_ingress_is_labeled_as_event_not_new_request() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    occurred = at(2)
    early = ingress("same", "wa", occurred, ingested_at=occurred)
    late = ingress(
        "same",
        "wa",
        occurred,
        source_id="event-late-duplicate",
        ingested_at=AS_OF + timedelta(hours=1),
    )

    metrics = {
        metric.name: metric
        for metric in calculate((), (), (early, late), (), account_mapping)
    }
    assert metrics["requests"].count == 1
    assert metrics["post_window_ingress_events"].count == 1


def test_old_root_denial_is_active_from_independent_window_ingress() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    old_root = operation(1, "wa", at(20), failure="expected_denial")
    denied_now = ingress("new-denial", "wa", at(2))

    metrics = {
        metric.name: metric
        for metric in calculate((old_root,), (), (denied_now,), (), account_mapping)
    }

    assert metrics["active_accounts"].count == 1
    assert metrics["requests"].count == 1
    assert metrics["logical_operations"].count == 0
    assert metrics["denial_incidence"].numerator == 0


def test_replay_status_and_duplicate_request_do_not_create_execution() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    rows = (
        ingress("request-1", "wa", at(2)),
        ingress("request-1", "wa", at(2), source_id="duplicate-event"),
        ingress("request-2", "wa", at(2), "same_key_replay"),
        ingress("request-3", "wa", at(2), "status_read"),
        ingress("request-4", "wa", at(2), "non_execution_read"),
        ingress("request-5", "wa", at(2), "unknown"),
        ingress("request-6", "wa", at(2), ingested_at=at(-2)),
    )

    metrics = {
        metric.name: metric for metric in calculate((), (), rows, (), account_mapping)
    }

    assert metrics["requests"].count == 5
    assert metrics["execution_intent_requests"].count == 1
    assert metrics["active_accounts"].count == 1
    assert metrics["non_execution_requests"].count == 3
    assert metrics["unknown_disposition_requests"].count == 1


def test_historical_observed_activity_is_partial_and_never_uses_ingress() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    historical = operation(1, "wa", at(3), basis="first_observed_evidence")

    metrics = {
        metric.name: metric
        for metric in calculate(
            (historical,),
            (),
            (),
            (),
            account_mapping,
            selected_window=window(basis="first_observed_evidence"),
        )
    }

    assert metrics["observed_accounts"].count == 1
    assert metrics["observed_accounts"].completeness == "partial"
    assert metrics["fault_incidence"].ratio is None
    assert "active_accounts" not in metrics
    assert "requests" not in metrics


def test_prior_retention_gap_keeps_returning_share_unknown() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    current = (ingress("now", "wa", at(2)),)
    prior = (ingress("prior", "wa", at(10)),)

    metrics = {
        metric.name: metric
        for metric in calculate(
            (),
            (),
            current,
            prior,
            account_mapping,
            prior_coverage=complete_coverage(at(9)),
        )
    }

    assert metrics["active_accounts"].count == 1
    assert metrics["returning_accounts"].count == 1
    assert metrics["returning_accounts"].ratio is None
    assert metrics["returning_accounts"].completeness == "partial"


def test_unresolved_age_skew_and_independent_recovery_dimensions() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    old = operation(
        1,
        "wa",
        at(5),
        unresolved_since=at(5),
        gateway_outcome="unknown",
        effect_state="confirmed",
        refund_state="completed",
        budget_release_state="pending",
    )
    skewed = operation(2, "wa", at(1), unresolved_since=at(-3))

    metrics = {
        metric.name: metric
        for metric in calculate((old, skewed), (), (), (), account_mapping)
    }

    assert metrics["unresolved_operations"].count == 2
    assert metrics["unresolved_age_days.1_7"].count == 1
    assert metrics["unresolved_clock_skew"].count == 1
    assert metrics["effect.confirmed"].count == 1
    assert metrics["refund.completed"].count == 1
    assert metrics["budget_release.pending"].count == 1
    assert metrics["gateway.unknown"].count == 2


def test_migration_uses_event_time_and_partial_sample_never_reports_exact_ratio() -> (
    None
):
    boundary = at(3)
    account_mapping = AccountMapping(
        "mapping-migration",
        (
            MappingInterval("wa", "A", "eligible", EARLIEST, boundary),
            MappingInterval("wa", "B", "eligible", boundary, None),
        ),
    )
    rows = (
        ingress("before", "wa", boundary - timedelta(microseconds=1)),
        ingress("after", "wa", boundary),
    )
    partial = Coverage(
        (SourceCoverage("insight_event", "available", EARLIEST, False),),
        enumeration_complete=False,
        truncated=True,
        gaps=("page_cap_reached",),
    )

    metrics = {
        metric.name: metric
        for metric in calculate((), (), rows, (), account_mapping, coverage=partial)
    }

    assert metrics["active_accounts"].count == 2
    assert metrics["active_accounts"].completeness == "partial"
    assert metrics["returning_accounts"].ratio is None
    assert metrics["fault_incidence"].denominator is None


def test_snapshot_before_window_end_cannot_claim_exact_incidence() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    early_cutoff = snapshot(at(2))

    metrics = {
        metric.name: metric
        for metric in calculate(
            (operation(1, "wa", at(3), failure="unexpected_fault"),),
            (),
            (ingress("request-1", "wa", at(3)),),
            (),
            account_mapping,
            read_snapshot=early_cutoff,
        )
    }

    assert metrics["fault_incidence"].numerator == 1
    assert metrics["fault_incidence"].ratio is None
    assert metrics["fault_incidence"].completeness == "partial"


def test_replay_only_root_never_adds_attempts_or_logical_operations() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    replay = replace(
        operation(1, "wa", at(3), attempt_ids=("attempt-1",)),
        execution_intent=False,
        replay_only=True,
    )

    metrics = {
        metric.name: metric
        for metric in calculate((replay,), (), (), (), account_mapping)
    }

    assert metrics["attempts"].count == 0
    assert metrics["logical_operations"].count == 0
    assert metrics["eligible_operations"].count == 0


def test_unresolved_age_uses_earliest_observation_not_later_status() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    row = operation(1, "wa", at(6), unresolved_since=at(2))

    metrics = {
        metric.name: metric for metric in calculate((row,), (), (), (), account_mapping)
    }

    assert metrics["unresolved_age_days.7_30"].count == 1
    assert metrics["unresolved_clock_skew"].count == 0


def test_pre_dispatch_denial_does_not_imply_an_ambiguous_attempt() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    denied = operation(
        1,
        "wa",
        at(3),
        failure="expected_denial",
        gateway_outcome="denied",
    )

    metrics = {
        metric.name: metric
        for metric in calculate((denied,), (), (), (), account_mapping)
    }

    assert metrics["attempts"].count == 0
    assert metrics["ambiguous_attempt_operations"].count == 0


@pytest.mark.parametrize(
    ("epoch", "anchor"),
    ((None, "anchor-1"), ("epoch-wa", None), (None, None)),
)
def test_missing_original_provenance_is_withheld_from_exact_incidence(
    epoch: str | None, anchor: str | None
) -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    unproven = replace(
        operation(1, "wa", at(3), failure="unexpected_fault", attempt_ids=("a-1",)),
        ownership_epoch_id=epoch,
        original_operation_anchor_id=anchor,
    )

    metrics = {
        metric.name: metric
        for metric in calculate((unproven,), (), (), (), account_mapping)
    }

    assert metrics["provenance_withheld_operations"].count == 1
    assert metrics["eligible_operations"].count == 0
    assert metrics["attempts"].count == 0
    assert metrics["logical_operations"].count == 0
    assert metrics["fault_incidence"].numerator == 0
    assert metrics["fault_incidence"].denominator is None
    assert metrics["fault_incidence"].completeness == "partial"


def test_hashed_tool_key_cannot_collide_with_literal_sha256_label() -> None:
    account_mapping = mapping(("wa", "A", "eligible"))
    slash_label = "tool/x"
    collision_label = f"sha256_{sha256(slash_label.encode()).hexdigest()}"
    rows = (
        operation(1, "wa", at(3), tool=slash_label),
        operation(2, "wa", at(3), tool=collision_label),
    )

    metrics = {
        metric.name: metric for metric in calculate(rows, (), (), (), account_mapping)
    }
    tool_counts = {
        name: metric.count
        for name, metric in metrics.items()
        if name.startswith("tool.")
    }

    assert len(tool_counts) == 2
    assert sorted(tool_counts.values()) == [1, 1]
    assert sum(tool_counts.values()) == metrics["eligible_operations"].count
