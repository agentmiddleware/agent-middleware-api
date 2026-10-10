"""Group already-authorized evidence without guessing operation identity."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from hashlib import sha256

from app.services.operation_insights.classify import classify
from app.services.operation_insights.contracts import (
    AccountMapping,
    Coverage,
    Evidence,
    EvidenceBatch,
    EvidenceRef,
    IngressObservation,
    Operation,
    StageTimestamp,
    TimeBasis,
)
from app.services.operation_insights.mapping import attribute


def _ref(row: Evidence) -> EvidenceRef:
    return EvidenceRef(
        row.source,
        row.source_id,
        row.wallet_id,
        row.ownership_epoch_id,
        row.original_operation_anchor_id,
    )


def _observed_at(row: Evidence) -> datetime | None:
    return row.occurred_at or row.ingested_at


def _sort_row(row: Evidence) -> tuple[bool, datetime | None, str, str]:
    return (_observed_at(row) is None, _observed_at(row), row.source, row.source_id)


def _timeline(rows: tuple[Evidence, ...]) -> tuple[StageTimestamp, ...]:
    source_ids = {(row.source, row.source_id) for row in rows}
    points = [
        StageTimestamp(
            row.event_kind or row.state_facts.dispatch_state or row.source,
            row.occurred_at,
            row.source,
            row.source_id,
        )
        for row in rows
        if row.occurred_at is not None
    ]
    points.extend(
        point
        for row in rows
        for point in row.stage_timestamps
        if (point.source, point.source_id) in source_ids
    )
    return tuple(
        sorted(
            set(points),
            key=lambda point: (point.at, point.source, point.source_id, point.stage),
        )
    )


def _coverage_gaps(coverage: Coverage) -> set[str]:
    gaps = set(coverage.gaps)
    for source in coverage.sources:
        gaps.update(source.gaps)
        if source.availability != "available":
            gaps.add(f"{source.source}_unavailable")
        if source.truncated or not source.enumeration_complete:
            gaps.add(f"{source.source}_incomplete")
    if coverage.truncated:
        gaps.add("enumeration_truncated")
    if not coverage.enumeration_complete:
        gaps.add("enumeration_incomplete")
    return gaps


def _group_operation(
    rows: tuple[Evidence, ...],
    mapping: AccountMapping,
    coverage: Coverage,
    *,
    heuristic_match: bool,
    edge_conflicts: set[str],
    edge_gaps: set[str],
    atomic: bool,
) -> Operation:
    first = rows[0]
    tools = {row.tool for row in rows if row.tool is not None}
    tool = next(iter(tools)) if len(tools) == 1 else None
    ingress_rows = tuple(row for row in rows if row.event_kind == "ingress")
    ingress = tuple(row for row in ingress_rows if row.request_id is not None)
    basis: TimeBasis = "ingress" if ingress_rows else "first_observed_evidence"
    timeline = _timeline(rows)
    all_observed = [stamp for row in rows if (stamp := _observed_at(row)) is not None]
    all_observed.extend(point.at for point in timeline)
    historical_roots = [
        row.occurred_at
        for row in rows
        if row.source == "idempotency" and row.occurred_at is not None
    ]
    starts = (
        [
            row.occurred_at
            for row in ingress
            if row.request_disposition == "execution_intent"
            and row.occurred_at is not None
        ]
        if ingress_rows
        else historical_roots or all_observed
    )
    first_seen = min(starts) if starts else None
    last_seen = max(all_observed) if all_observed else None
    account = attribute(first.wallet_id, first_seen, mapping)
    request_ids = tuple(sorted({row.request_id for row in ingress if row.request_id}))
    attempts = {row.source_id for row in rows if row.source == "dispatch"}
    attempts.update(
        row.attempt_id
        for row in rows
        if row.event_kind == "attempt" and row.attempt_id is not None
    )
    attempt_ids = tuple(sorted(attempts))
    observations = tuple(
        sorted(
            {
                IngressObservation(
                    row.request_id, row.occurred_at, row.request_disposition
                )
                for row in ingress
                if row.request_id is not None
                and row.occurred_at is not None
                and row.request_disposition is not None
            },
            key=lambda item: (item.occurred_at, item.request_id, item.disposition),
        )
    )
    dispositions = {row.request_disposition for row in ingress}
    gaps = _coverage_gaps(coverage) | edge_gaps
    conflicts = set(edge_conflicts)
    if not atomic:
        gaps.add("non_atomic_snapshot")
    if any(row.occurred_at is None for row in rows):
        gaps.add("occurrence_time_missing")
    if first_seen is None and not all_observed:
        gaps.add("observation_time_missing")
    if ingress_rows and any(row.request_id is None for row in ingress_rows):
        gaps.add("ingress_identity_missing")
    if ingress_rows and not any(
        row.request_disposition == "execution_intent" for row in ingress
    ):
        gaps.add("execution_intent_ingress_missing")
    if ingress_rows and any(row.occurred_at is None for row in ingress_rows):
        gaps.add("ingress_time_missing")
    if len(tools) > 1:
        conflicts.add("tool_mismatch")
    event_rows = tuple(row for row in rows if row.source == "insight_event")
    metadata: dict[str, str | None] = {}
    for field in ("environment", "server_release", "deployment", "client_version"):
        values = {getattr(row, field) for row in event_rows}
        present = values - {None}
        if len(present) > 1:
            conflicts.add(f"{field}_metadata_conflict")
        if None in values:
            gaps.add(f"{field}_metadata_missing")
        metadata[field] = next(iter(present)) if len(values) == 1 and present else None
    if heuristic_match:
        gaps.add("heuristic_correlation_candidate")
    source_ids = {(row.source, row.source_id) for row in rows}
    if any(
        (point.source, point.source_id) not in source_ids
        for row in rows
        for point in row.stage_timestamps
    ):
        gaps.add("stage_timestamp_unreferenced")
    if any(
        row.ingested_at is not None
        and row.occurred_at is not None
        and row.ingested_at < row.occurred_at
        for row in rows
    ):
        conflicts.add("ingestion_before_occurrence")
    timed_rows = tuple(
        row
        for row in rows
        if row.occurred_at is not None and row.ingested_at is not None
    )
    if len(timed_rows) > 1:
        occurred_order = tuple(
            _ref(row)
            for row in sorted(
                timed_rows,
                key=lambda row: (row.occurred_at, row.source, row.source_id),
            )
        )
        ingestion_order = tuple(
            _ref(row)
            for row in sorted(
                timed_rows,
                key=lambda row: (row.ingested_at, row.source, row.source_id),
            )
        )
        if occurred_order != ingestion_order:
            gaps.add("ingestion_order_differs")
    logical_ids = {row.logical_operation_id for row in rows if row.logical_operation_id}
    if len(logical_ids) > 1:
        conflicts.add("logical_operation_id_conflict")
    dispositions_by_request: dict[str, set[str | None]] = defaultdict(set)
    for row in ingress:
        if row.request_id is not None:
            dispositions_by_request[row.request_id].add(row.request_disposition)
    if any(len(values) > 1 for values in dispositions_by_request.values()):
        conflicts.add("request_disposition_conflict")
    stage_times: dict[str, list[datetime]] = defaultdict(list)
    per_source_stage: dict[tuple[str, str, str], set[datetime]] = defaultdict(set)
    for point in timeline:
        stage_times[point.stage].append(point.at)
        per_source_stage[(point.source, point.source_id, point.stage)].add(point.at)
    if (
        stage_times["prepared"]
        and stage_times["dispatch_claimed"]
        and min(stage_times["dispatch_claimed"]) < min(stage_times["prepared"])
    ):
        conflicts.add("stage_time_order_conflict")
    if any(len(values) > 1 for values in per_source_stage.values()):
        conflicts.add("stage_timestamp_conflict")
    key_parts = (
        first.wallet_id or "",
        first.ownership_epoch_id or "",
        first.original_operation_anchor_id or "",
    )
    key = "\x1f".join(key_parts)
    operation = Operation(
        "operation-" + sha256(key.encode()).hexdigest()[:24],
        first.wallet_id,
        basis,
        request_ids=request_ids,
        attempt_ids=attempt_ids,
        logical_operation_id=next(iter(logical_ids)) if len(logical_ids) == 1 else None,
        correlation_status=(
            "explicit"
            if len(rows) > 1 or logical_ids
            else "ambiguous"
            if heuristic_match
            else "unavailable"
        ),
        account_id=account.account_id,
        account_class=account.account_class,
        mapping_status=account.mapping_status,
        tool=tool,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        environment=metadata["environment"],
        server_release=metadata["server_release"],
        deployment=metadata["deployment"],
        client_version=metadata["client_version"],
        stage_timestamps=timeline,
        evidence_refs=tuple(_ref(row) for row in rows),
        evidence_gaps=tuple(sorted(gaps)),
        conflicts=tuple(sorted(conflicts)),
        execution_intent=True
        if "execution_intent" in dispositions
        else (False if ingress else None),
        replay_only=True
        if dispositions == {"same_key_replay"}
        else (False if ingress else None),
        ownership_epoch_id=first.ownership_epoch_id,
        original_operation_anchor_id=first.original_operation_anchor_id,
        ingress_observations=observations,
    )
    return classify(operation, rows)


def inspect_operations(
    batch: EvidenceBatch, mapping: AccountMapping
) -> tuple[Operation, ...]:
    """Inspect scoped roots; never correlate by key, request ID or nearby time."""
    rows = tuple(sorted(batch.rows, key=_sort_row))
    if any(
        row.wallet_id is None
        or row.ownership_epoch_id is None
        or row.original_operation_anchor_id is None
        for row in rows
    ):
        raise ValueError("inspector requires authorized wallet and original provenance")
    by_anchor: dict[tuple[str, str, str], list[Evidence]] = defaultdict(list)
    for row in rows:
        assert row.wallet_id is not None
        assert row.ownership_epoch_id is not None
        assert row.original_operation_anchor_id is not None
        by_anchor[
            (row.wallet_id, row.ownership_epoch_id, row.original_operation_anchor_id)
        ].append(row)
    groups = [tuple(anchor_rows) for _, anchor_rows in sorted(by_anchor.items())]
    request_groups: dict[str, set[int]] = defaultdict(set)
    for index, group in enumerate(groups):
        for row in group:
            if row.request_id is not None:
                request_groups[row.request_id].add(index)
    heuristic_groups = {
        index
        for indices in request_groups.values()
        if len(indices) > 1
        for index in indices
    }
    results = []
    for index, group in enumerate(groups):
        group_refs = {_ref(row) for row in group}
        edge_conflicts: set[str] = set()
        edge_gaps: set[str] = set()
        for row in group:
            for edge in row.edges:
                if (
                    edge.wallet_id != row.wallet_id
                    or edge.ownership_epoch_id != row.ownership_epoch_id
                    or edge.original_operation_anchor_id
                    != row.original_operation_anchor_id
                ):
                    edge_conflicts.add("cross_scope_edge")
                elif edge not in group_refs:
                    edge_gaps.add("dangling_edge")
        group = tuple(sorted(group, key=_sort_row))
        results.append(
            _group_operation(
                group,
                mapping,
                batch.coverage,
                heuristic_match=index in heuristic_groups,
                edge_conflicts=edge_conflicts,
                edge_gaps=edge_gaps,
                atomic=batch.snapshot.atomic,
            )
        )
    return tuple(sorted(results, key=lambda item: item.operation_id))
