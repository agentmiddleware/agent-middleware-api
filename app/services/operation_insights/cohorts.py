"""Observed, bounded cohort arithmetic over already-authorized projections.

Counts are lower bounds when source enumeration or retention is incomplete.
Historical observed activity never becomes an ingress denominator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
import re

from app.services.operation_insights.contracts import (
    AccountMapping,
    Completeness,
    Coverage,
    Evidence,
    Metric,
    Operation,
    Snapshot,
    Window,
)
from app.services.operation_insights.mapping import attribute


_EXCLUDED = ("internal", "demo", "CI", "monitoring")
_METRIC_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _complete(
    coverage: Coverage | None, snapshot: Snapshot, start: datetime, end: datetime
) -> bool:
    return bool(
        coverage is not None
        and snapshot.atomic
        and snapshot.cutoff >= end
        and coverage.enumeration_complete
        and not coverage.truncated
        and not coverage.consistency_flags
        and not coverage.skew_flags
        and not coverage.gaps
        and coverage.sources
        and all(
            source.availability == "available"
            and source.enumeration_complete
            and not source.truncated
            and not source.consistency_flags
            and not source.skew_flags
            and not source.gaps
            and source.earliest_retained_at is not None
            and source.earliest_retained_at <= start
            for source in coverage.sources
        )
    )


def _key(prefix: str, value: str | None) -> str:
    if value is None:
        return f"{prefix}.__missing__"
    label = value
    direct = f"{prefix}.{label}"
    if (
        direct != f"{prefix}.__missing__"
        and not label.startswith("sha256_")
        and _METRIC_ID.fullmatch(direct)
    ):
        return direct
    # A stable bounded key avoids truncation collisions and raw free-text labels.
    return f"{prefix}.sha256_{sha256(label.encode()).hexdigest()}"


def _operations(
    operations: tuple[Operation, ...], window: Window, snapshot: Snapshot
) -> tuple[Operation, ...]:
    selected: dict[tuple[bool, str | None, str | None, str], Operation] = {}
    for row in operations:
        if row.time_basis != window.time_basis:
            raise ValueError("cohort time bases must remain separate")
        if window.time_basis == "ingress" and row.execution_intent is not True:
            continue
        if (
            row.first_seen_at is None
            or not window.start <= row.first_seen_at < window.end
        ):
            continue
        if row.first_seen_at > snapshot.cutoff:
            continue
        proven = (
            row.wallet_id is not None
            and row.ownership_epoch_id is not None
            and row.original_operation_anchor_id is not None
        )
        anchor = row.original_operation_anchor_id if proven else row.operation_id
        assert anchor is not None
        key = (proven, row.wallet_id, row.ownership_epoch_id, anchor)
        prior = selected.get(key)
        if prior is not None and prior != row:
            raise ValueError("conflicting operation projections in snapshot")
        selected[key] = row
    return tuple(selected.values())


def _requests(
    events: tuple[Evidence, ...], window: Window, snapshot: Snapshot
) -> tuple[tuple[Evidence, bool], ...]:
    selected: dict[tuple[str, str, str], list[Evidence]] = defaultdict(list)
    for row in events:
        if (
            row.event_kind != "ingress"
            or row.wallet_id is None
            or row.ownership_epoch_id is None
            or row.original_operation_anchor_id is None
            or row.request_id is None
            or row.request_disposition is None
            or row.occurred_at is None
        ):
            raise ValueError("cohort ingress requires scoped request evidence")
        if not window.start <= row.occurred_at < window.end:
            continue
        if row.ingested_at is not None and row.ingested_at > snapshot.cutoff:
            continue
        if row.occurred_at > snapshot.cutoff:
            continue
        selected[(row.wallet_id, row.ownership_epoch_id, row.request_id)].append(row)
    result = []
    for rows in selected.values():
        first = min(rows, key=lambda row: (row.occurred_at, row.source, row.source_id))
        conflicting = (
            len(
                {
                    (row.original_operation_anchor_id, row.request_disposition)
                    for row in rows
                }
            )
            > 1
        )
        result.append((first, conflicting))
    return tuple(result)


def _eligible_accounts_from_events(
    events: tuple[tuple[Evidence, bool], ...], mapping: AccountMapping
) -> set[str]:
    result = set()
    for row, conflicting in events:
        if conflicting or row.request_disposition != "execution_intent":
            continue
        account = attribute(row.wallet_id, row.occurred_at, mapping)
        if account.mapping_status == "mapped" and account.account_class == "eligible":
            assert account.account_id is not None
            result.add(account.account_id)
    return result


def compute_metrics(
    current: tuple[Operation, ...],
    prior: tuple[Operation, ...],
    current_window_ingress: tuple[Evidence, ...],
    prior_window_ingress: tuple[Evidence, ...],
    mapping: AccountMapping,
    window: Window,
    snapshot: Snapshot,
    coverage: Coverage,
    prior_coverage: Coverage | None = None,
    *,
    current_evidence: tuple[Evidence, ...] = (),
) -> tuple[Metric, ...]:
    """Calculate one 7/30-day cohort without mixing observed and ingress time."""
    duration = window.end - window.start
    if duration not in (timedelta(days=7), timedelta(days=30)):
        raise ValueError("cohort window must be exactly 7 or 30 days")
    prior_window = Window(window.start - duration, window.start, window.time_basis)
    current_rows = _operations(current, window, snapshot)
    prior_rows = _operations(prior, prior_window, snapshot)
    provenance_withheld = sum(
        row.wallet_id is None
        or row.ownership_epoch_id is None
        or row.original_operation_anchor_id is None
        for row in current_rows
    )
    if window.time_basis == "first_observed_evidence" and (
        current_window_ingress or prior_window_ingress
    ):
        raise ValueError("historical observed activity cannot contain ingress")
    events = _requests(current_window_ingress, window, snapshot)
    previous_events = _requests(prior_window_ingress, prior_window, snapshot)
    exact = (
        not provenance_withheld
        and window.time_basis == "ingress"
        and _complete(coverage, snapshot, window.start, window.end)
    )
    prior_exact = window.time_basis == "ingress" and _complete(
        prior_coverage, snapshot, prior_window.start, prior_window.end
    )
    completeness: Completeness = "complete" if exact else "partial"
    returning_completeness: Completeness = (
        "complete" if exact and prior_exact else "partial"
    )
    metrics: list[Metric] = []

    def add(
        name: str,
        count: int,
        grain: str,
        *,
        numerator: int | None = None,
        denominator: int | None = None,
        unknown: int = 0,
        excluded: int = 0,
        status: Completeness = completeness,
    ) -> None:
        if status != "complete":
            denominator = None
        ratio = (
            numerator / denominator
            if status == "complete"
            and numerator is not None
            and denominator is not None
            and denominator != 0
            else None
        )
        metrics.append(
            Metric(
                name,
                count,
                numerator,
                denominator,
                ratio,
                grain,
                window,
                unknown,
                excluded,
                status,
            )
        )

    excluded_accounts: dict[str, set[str]] = {kind: set() for kind in _EXCLUDED}
    unknown_wallets: set[tuple[str, str | None]] = set()
    if window.time_basis == "ingress":
        active = _eligible_accounts_from_events(events, mapping)
        prior_active = _eligible_accounts_from_events(previous_events, mapping)
        disposition_counts: Counter[str] = Counter()
        unknown_requests = 0
        excluded_requests = 0
        for event_row, conflicting in events:
            attribution = attribute(event_row.wallet_id, event_row.occurred_at, mapping)
            if attribution.mapping_status != "mapped":
                unknown_requests += 1
                assert event_row.wallet_id is not None
                unknown_wallets.add((event_row.wallet_id, event_row.ownership_epoch_id))
            elif attribution.account_class != "eligible":
                excluded_requests += 1
                assert attribution.account_id is not None
                excluded_accounts[attribution.account_class].add(attribution.account_id)
            disposition = "unknown" if conflicting else event_row.request_disposition
            assert disposition is not None
            disposition_counts[disposition] += 1
        add(
            "requests",
            len(events),
            "request",
            unknown=unknown_requests,
            excluded=excluded_requests,
        )
        add(
            "execution_intent_requests",
            disposition_counts["execution_intent"],
            "request",
        )
        add(
            "non_execution_requests",
            sum(
                disposition_counts[kind]
                for kind in ("same_key_replay", "status_read", "non_execution_read")
            ),
            "request",
        )
        add("unknown_disposition_requests", disposition_counts["unknown"], "request")
        add("active_accounts", len(active), "account")
        late_ingress = {
            (row.source, row.source_id)
            for row in current_window_ingress
            if row.occurred_at is not None
            and window.start <= row.occurred_at < window.end
            and row.ingested_at is not None
            and window.end <= row.ingested_at <= snapshot.cutoff
        }
        add("post_window_ingress_events", len(late_ingress), "event")
    else:
        active = set()
        prior_active = set()
        for group, rows in ((active, current_rows), (prior_active, prior_rows)):
            for observed_row in rows:
                attribution = attribute(
                    observed_row.wallet_id, observed_row.first_seen_at, mapping
                )
                if (
                    attribution.mapping_status == "mapped"
                    and attribution.account_class == "eligible"
                ):
                    assert attribution.account_id is not None
                    group.add(attribution.account_id)
        add("observed_accounts", len(active), "account")
    returning = active & prior_active
    add(
        "returning_accounts",
        len(returning),
        "account",
        numerator=len(returning),
        denominator=len(active),
        status=returning_completeness,
    )

    eligible: list[tuple[Operation, str]] = []
    add("provenance_withheld_operations", provenance_withheld, "operation")
    for operation_row in current_rows:
        if (
            operation_row.wallet_id is None
            or operation_row.ownership_epoch_id is None
            or operation_row.original_operation_anchor_id is None
        ):
            continue
        attribution = attribute(
            operation_row.wallet_id, operation_row.first_seen_at, mapping
        )
        if attribution.mapping_status != "mapped":
            if operation_row.wallet_id is not None:
                unknown_wallets.add(
                    (operation_row.wallet_id, operation_row.ownership_epoch_id)
                )
            continue
        assert attribution.account_id is not None
        if attribution.account_class in _EXCLUDED:
            excluded_accounts[attribution.account_class].add(attribution.account_id)
            continue
        eligible.append((operation_row, attribution.account_id))
    add("unknown_wallet_attributions", len(unknown_wallets), "wallet")
    for kind in _EXCLUDED:
        add(f"excluded_{kind}_accounts", len(excluded_accounts[kind]), "account")
    add("eligible_operations", len(eligible), "operation")

    attempts = {
        (
            row.wallet_id,
            row.ownership_epoch_id,
            row.original_operation_anchor_id,
            attempt,
        )
        for row, _ in eligible
        for attempt in row.attempt_ids
    }
    add("attempts", len(attempts), "attempt")
    add(
        "ambiguous_attempt_operations",
        sum(
            1
            for row, _ in eligible
            if "attempt_identity_ambiguous" in row.evidence_gaps
            or "attempt_identity_ambiguous" in row.conflicts
        ),
        "operation",
    )
    add(
        "admitted_accounts",
        len({account for row, account in eligible if row.attempt_ids}),
        "account",
    )
    add(
        "gateway_completed_accounts",
        len(
            {
                account
                for row, account in eligible
                if row.gateway_outcome in ("succeeded", "failed", "denied")
            }
        ),
        "account",
    )
    add(
        "gateway_succeeded_accounts",
        len(
            {account for row, account in eligible if row.gateway_outcome == "succeeded"}
        ),
        "account",
    )
    logical: dict[
        tuple[str, str | None, str | None, str | None, str], list[Operation]
    ] = defaultdict(list)
    uncorrelatable = 0
    for row, account in eligible:
        if (
            row.logical_operation_id is None
            or row.correlation_status != "explicit"
            or (window.time_basis == "ingress" and row.execution_intent is not True)
        ):
            uncorrelatable += 1
            continue
        logical[
            (
                account,
                row.wallet_id,
                row.ownership_epoch_id,
                row.tool,
                row.logical_operation_id,
            )
        ].append(row)
    add("uncorrelatable_operations", uncorrelatable, "operation")
    add("logical_operations", len(logical), "logical_operation")
    fault = sum(
        any(row.observed_fault is True for row in rows) for rows in logical.values()
    )
    denial = sum(
        any(row.observed_denial is True for row in rows) for rows in logical.values()
    )
    unknown_classification = sum(
        not any(
            row.observed_fault is True or row.observed_denial is True for row in rows
        )
        and any(row.failure_class in ("unknown", "conflicting") for row in rows)
        for rows in logical.values()
    )
    for name, numerator in (("fault_incidence", fault), ("denial_incidence", denial)):
        add(
            name,
            numerator,
            "logical_operation",
            numerator=numerator,
            denominator=len(logical),
            unknown=unknown_classification,
        )
    add(
        "impacted_accounts",
        len({account for row, account in eligible if row.observed_fault is True}),
        "account",
    )
    add(
        "denied_accounts",
        len({account for row, account in eligible if row.observed_denial is True}),
        "account",
    )

    dimensions: dict[str, Counter[str]] = {
        prefix: Counter()
        for prefix in (
            "reason",
            "stage",
            "tool",
            "gateway",
            "effect",
            "refund",
            "budget_release",
            "deployment",
            "release",
        )
    }
    unresolved_accounts: set[str] = set()
    unresolved_age: Counter[str] = Counter()
    unresolved_count = 0
    post_window_updates = 0
    late_evidence = {
        (
            row.source,
            row.source_id,
            row.wallet_id,
            row.ownership_epoch_id,
            row.original_operation_anchor_id,
        )
        for row in current_evidence
        if row.ingested_at is not None
        and window.end <= row.ingested_at <= snapshot.cutoff
    }
    for row, account in eligible:
        for prefix, value in (
            (
                "reason",
                None if "reason_code_conflict" in row.conflicts else row.reason_code,
            ),
            ("stage", row.failure_stage),
            ("tool", row.tool),
            ("gateway", row.gateway_outcome),
            ("effect", row.effect_state),
            ("refund", row.refund_state),
            ("budget_release", row.budget_release_state),
            ("deployment", row.deployment),
            ("release", row.server_release),
        ):
            dimensions[prefix][_key(prefix, value)] += 1
        if (row.last_seen_at is not None and row.last_seen_at >= window.end) or any(
            (
                ref.source,
                ref.source_id,
                ref.wallet_id,
                ref.ownership_epoch_id,
                ref.original_operation_anchor_id,
            )
            in late_evidence
            for ref in row.evidence_refs
        ):
            post_window_updates += 1
        unresolved = bool(
            row.unresolved_since is not None
            or row.conflicts
            or row.gateway_outcome in ("unknown", "conflicting")
            or row.effect_state in ("unknown", "conflicting")
            or row.refund_state in ("unknown", "conflicting", "failed", "pending")
            or row.budget_release_state
            in ("unknown", "conflicting", "failed", "pending")
        )
        if not unresolved:
            continue
        unresolved_count += 1
        unresolved_accounts.add(account)
        observed_times = [
            point
            for point in (row.first_seen_at, row.unresolved_since)
            if point is not None
        ]
        observed_times.extend(point.at for point in row.stage_timestamps)
        earliest = min(observed_times) if observed_times else None
        if earliest is None:
            unresolved_age["unknown"] += 1
            continue
        if row.unresolved_since is not None and row.unresolved_since > snapshot.cutoff:
            unresolved_age["skew"] += 1
            continue
        age = snapshot.cutoff - earliest
        if age < timedelta(0):
            unresolved_age["skew"] += 1
        elif age < timedelta(days=1):
            unresolved_age["lt1"] += 1
        elif age < timedelta(days=7):
            unresolved_age["1_7"] += 1
        elif age < timedelta(days=30):
            unresolved_age["7_30"] += 1
        else:
            unresolved_age["gte30"] += 1
    add("unresolved_operations", unresolved_count, "operation")
    add("unresolved_accounts", len(unresolved_accounts), "account")
    add("unresolved_clock_skew", unresolved_age["skew"], "operation")
    add("post_window_observed_updates", post_window_updates, "operation")
    for bucket in ("lt1", "1_7", "7_30", "gte30", "unknown"):
        add(f"unresolved_age_days.{bucket}", unresolved_age[bucket], "operation")
    for prefix, counts in dimensions.items():
        for name, count in sorted(counts.items()):
            add(name, count, "operation")
    return tuple(metrics)
