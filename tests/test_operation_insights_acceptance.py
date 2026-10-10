"""Golden, synthetic operator insight handoff checks."""

import csv
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.operation_insights.cohorts import compute_metrics
from app.services.operation_insights.contracts import (
    AccountMapping,
    AuthorizedOwnershipEpoch,
    Coverage,
    Evidence,
    EvidenceBatch,
    EvidenceStateFacts,
    Limits,
    MappingInterval,
    Report,
    Scope,
    Snapshot,
    SourceCoverage,
    Window,
)
from app.services.operation_insights.export import build_report, write_bundle
from app.services.operation_insights.inspect import inspect_operations


INCIDENTS = json.loads(
    (Path(__file__).parent / "fixtures/operation_insights/incidents.json").read_text()
)
UTC = timezone.utc
START = datetime(2026, 10, 1, tzinfo=UTC)
END = START + timedelta(days=7)
SNAPSHOT = Snapshot(END, "synthetic-snapshot", True, None)
WINDOW = Window(START, END, "first_observed_evidence")
MAPPING = AccountMapping(
    "synthetic-mapping-1",
    (
        MappingInterval("wallet-primary", "account-primary", "eligible", START, None),
        MappingInterval("wallet-demo", "account-demo", "demo", START, None),
    ),
)


def _golden_report() -> tuple[Report, Scope]:
    # The fixture's confirmed effect is hypothetical independently verified
    # evidence for classifier acceptance. Current capture cannot prove it.
    rows = tuple(
        Evidence(
            source=item["source"],
            source_id=f"{incident['name']}-{item['id']}",
            wallet_id="wallet-primary",
            ownership_epoch_id="epoch-primary",
            original_operation_anchor_id=f"anchor-{incident['name']}",
            tool="partner.notes.write",
            occurred_at=START + timedelta(hours=item["at"]),
            state_facts=EvidenceStateFacts(**item["facts"]),
            reason_code=item.get("reason"),
        )
        for incident in INCIDENTS
        for item in incident["rows"]
    ) + (
        Evidence(
            "idempotency",
            "unmapped-observation",
            "wallet-unmapped",
            ownership_epoch_id="epoch-unmapped",
            original_operation_anchor_id="anchor-unmapped",
            occurred_at=START + timedelta(hours=8),
        ),
        Evidence(
            "idempotency",
            "demo-observation",
            "wallet-demo",
            ownership_epoch_id="epoch-demo",
            original_operation_anchor_id="anchor-demo",
            occurred_at=START + timedelta(hours=9),
        ),
    )
    coverage = Coverage(
        sources=(
            SourceCoverage(
                "audit",
                availability="unavailable",
                gaps=("audit_anchor_unverified",),
            ),
            SourceCoverage(
                "idempotency",
                availability="available",
                gaps=("surviving_roots_only", "retention_unverified"),
            ),
        ),
        gaps=(
            "historical_retention_unverified",
            "legacy_unanchored_evidence_withheld",
            "audit_anchor_unverified",
            "refund_work_item_unreadable",
        ),
    )
    operations = inspect_operations(EvidenceBatch(rows, SNAPSHOT, coverage), MAPPING)
    metrics = compute_metrics(
        operations, (), (), (), MAPPING, WINDOW, SNAPSHOT, coverage
    )
    scope = Scope(
        wallet_ids=frozenset({"wallet-primary", "wallet-demo", "wallet-unmapped"}),
        authorized_ownership_epochs=tuple(
            AuthorizedOwnershipEpoch(wallet, epoch, START, END)
            for wallet, epoch in (
                ("wallet-primary", "epoch-primary"),
                ("wallet-demo", "epoch-demo"),
                ("wallet-unmapped", "epoch-unmapped"),
            )
        ),
    )
    report = Report(
        report_id="synthetic-golden-report",
        generated_at=END,
        as_of=END,
        snapshot_cutoff=SNAPSHOT.cutoff,
        window_start=START,
        window_end=END,
        time_basis="first_observed_evidence",
        environment=None,
        source_release=None,
        coverage=coverage,
        mapping_version=MAPPING.version,
        exclusions=("internal", "demo", "CI", "monitoring"),
        operations=operations,
        evidence=rows,
        metrics=metrics,
        authorized_scope=scope,
    )
    return report, scope


@pytest.mark.asyncio
async def test_golden_report_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    side_effects = (
        "app.services.mcp_dispatch_attempts.McpDispatchAttemptService.prepare",
        "app.services.mcp_dispatch_attempts.McpDispatchAttemptService.claim_dispatch",
        "app.services.mcp_dispatch_attempts.McpDispatchAttemptService.complete",
        "app.services.mcp_dispatch_attempts.McpDispatchAttemptService.mark_debit_refunded",
        "app.services.wallet_engine.WalletEngine.transfer",
    )
    forbidden = []
    for path in side_effects:
        spy = AsyncMock(side_effect=AssertionError("insight_business_mutation"))
        monkeypatch.setattr(path, spy)
        forbidden.append(spy)
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    seed, scope = _golden_report()
    session = object()
    windows: list[Window] = []

    async def read_synthetic(
        requested_scope: Scope,
        window: Window,
        limits: Limits,
        requested_session: object,
    ) -> EvidenceBatch:
        assert requested_scope is scope
        assert requested_session is session
        windows.append(window)
        return EvidenceBatch(
            seed.evidence if window == WINDOW else (), SNAPSHOT, seed.coverage
        )

    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence", read_synthetic
    )
    report = await build_report(scope, WINDOW, Limits(), MAPPING, session)
    assert windows == [
        WINDOW,
        Window(START - timedelta(days=7), START, "first_observed_evidence"),
    ]
    by_anchor = {
        operation.original_operation_anchor_id: operation
        for operation in report.operations
    }
    assert len(report.operations) == len(INCIDENTS) + 2
    assert len(report.evidence) == sum(len(item["rows"]) for item in INCIDENTS) + 2
    for incident in INCIDENTS:
        operation = by_anchor[f"anchor-{incident['name']}"]
        expected = incident["expected"]
        for state in (
            "gateway_outcome",
            "effect_state",
            "refund_state",
            "budget_release_state",
            "failure_class",
            "next_action",
        ):
            assert getattr(operation, state) == expected[state]
        assert len(operation.evidence_refs) == len(incident["rows"])
        assert len(operation.attempt_ids) == expected["attempts"]
        assert operation.unresolved_since is not None
        assert operation.next_action in {"inspect", "reconcile", "manual_review"}
        assert "historical_retention_unverified" in operation.evidence_gaps
        assert "refund_work_item_unreadable" in operation.evidence_gaps
        if any(row["source"] == "dispatch" for row in incident["rows"]) and not any(
            row["source"] == "receipt" for row in incident["rows"]
        ):
            assert "receipt_missing" in operation.evidence_gaps

    metrics = {metric.name: metric for metric in report.metrics}
    assert metrics["eligible_operations"].count == len(INCIDENTS)
    assert metrics["unknown_wallet_attributions"].count == 1
    assert metrics["excluded_demo_accounts"].count == 1
    assert metrics["unresolved_operations"].count == len(INCIDENTS)
    assert metrics["fault_incidence"].denominator is None
    assert metrics["fault_incidence"].ratio is None

    directory = tmp_path / "bundle"
    manifest = write_bundle(report, directory, scope=scope, session=session)
    payload = json.loads((directory / "report.json").read_text())
    assert payload["time_basis"] == "first_observed_evidence"
    assert payload["environment"] is None
    assert payload["source_release"] is None
    assert payload["coverage"]["gaps"]
    assert manifest.completeness == "partial"
    assert {entry.name: entry.row_count for entry in manifest.files} == {
        "report.json": 1,
        "report.csv": 1,
        "operations.csv": len(report.operations),
        "evidence.csv": len(report.evidence),
        "aggregates.csv": len(report.metrics),
    }
    for entry in manifest.files:
        assert hashlib.sha256((directory / entry.name).read_bytes()).hexdigest() == (
            entry.sha256
        )
    manifest_payload = json.loads((directory / "manifest.json").read_text())
    assert manifest_payload == json.loads(json.dumps(asdict(manifest)))
    with (directory / "report.csv").open(newline="", encoding="utf-8") as handle:
        report_rows = list(csv.DictReader(handle))
    assert len(report_rows) == 1
    envelope = report_rows[0]
    for field in (
        "report_id",
        "time_basis",
        "mapping_version",
        "window_start",
        "window_end",
        "snapshot_cutoff",
    ):
        assert envelope[field] == payload[field]
    assert envelope["completeness"] == manifest.completeness
    assert int(envelope["operation_count"]) == len(payload["operations"])
    assert int(envelope["evidence_count"]) == len(payload["evidence"])
    assert int(envelope["metric_count"]) == len(payload["metrics"])
    for filename, expected in (
        ("operations.csv", payload["operations"]),
        ("evidence.csv", payload["evidence"]),
        ("aggregates.csv", payload["metrics"]),
    ):
        with (directory / filename).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == len(expected)
        assert {row["report_id"] for row in rows} == {report.report_id}
        if filename == "operations.csv":
            by_id = {item["operation_id"]: item for item in expected}
            assert {row["operation_id"] for row in rows} == set(by_id)
            for row in rows:
                item = by_id[row["operation_id"]]
                for field in (
                    "gateway_outcome",
                    "effect_state",
                    "refund_state",
                    "budget_release_state",
                    "failure_class",
                    "next_action",
                    "mapping_status",
                ):
                    assert row[field] == item[field]
                assert json.loads(row["evidence_refs"]) == item["evidence_refs"]
        elif filename == "evidence.csv":
            by_id = {item["source_id"]: item for item in expected}
            assert {row["source_id"] for row in rows} == set(by_id)
            for row in rows:
                item = by_id[row["source_id"]]
                assert row["source"] == item["source"]
                assert row["wallet_id"] == item["wallet_id"]
                assert json.loads(row["state_facts"]) == item["state_facts"]
                assert row["operation_id"] in {
                    operation["operation_id"] for operation in payload["operations"]
                }
        else:
            by_name = {item["name"]: item for item in expected}
            assert {row["name"] for row in rows} == set(by_name)
            for row in rows:
                item = by_name[row["name"]]
                assert int(row["count"]) == item["count"]
                assert row["completeness"] == item["completeness"]
                assert int(row["unknown_count"]) == item["unknown_count"]
                assert int(row["excluded_count"]) == item["excluded_count"]
    for spy in forbidden:
        spy.assert_not_awaited()


def test_golden_report_rejects_narrower_scope_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    report, _ = _golden_report()
    narrower = Scope(wallet_ids=frozenset({"wallet-primary"}))
    with pytest.raises(ValueError, match="invalid_insight_report"):
        write_bundle(report, tmp_path / "bundle", scope=narrower, session=object())
    assert tuple(tmp_path.iterdir()) == ()


def test_complete_ingress_cohort_keeps_late_evidence_and_prior_gap_separate() -> None:
    prior_start = START - timedelta(days=7)
    snapshot = Snapshot(END + timedelta(days=2), "late-snapshot", True, None)
    mapping = AccountMapping(
        "synthetic-ingress-mapping",
        (
            MappingInterval("wallet-a", "account-a", "eligible", prior_start, None),
            MappingInterval("wallet-b", "account-b", "eligible", prior_start, None),
            MappingInterval("wallet-demo", "account-demo", "demo", prior_start, None),
        ),
    )

    def ingress(
        wallet: str, anchor: str, request: str, when: datetime, disposition: str
    ) -> Evidence:
        return Evidence(
            "insight_event",
            f"event-{request}",
            wallet,
            ownership_epoch_id=f"epoch-{wallet}",
            original_operation_anchor_id=anchor,
            request_id=request,
            occurred_at=when,
            ingested_at=when,
            event_kind="ingress",
            request_disposition=disposition,
        )

    current_ingress = (
        ingress("wallet-a", "anchor-a", "request-a", START, "execution_intent"),
        replace(
            ingress(
                "wallet-b",
                "anchor-b-current",
                "request-b",
                START + timedelta(days=1),
                "execution_intent",
            ),
            ingested_at=END + timedelta(days=1),
        ),
        ingress(
            "wallet-demo",
            "anchor-demo",
            "request-demo",
            START + timedelta(days=2),
            "execution_intent",
        ),
        ingress(
            "wallet-unknown",
            "anchor-unknown",
            "request-unknown",
            START + timedelta(days=3),
            "execution_intent",
        ),
        ingress(
            "wallet-a",
            "anchor-a",
            "request-replay",
            START + timedelta(days=4),
            "same_key_replay",
        ),
    )
    prior_ingress = (
        ingress(
            "wallet-b",
            "anchor-b-prior",
            "request-b-prior",
            prior_start + timedelta(days=1),
            "execution_intent",
        ),
    )
    late_terminal = Evidence(
        "insight_event",
        "event-a-terminal",
        "wallet-a",
        ownership_epoch_id="epoch-wallet-a",
        original_operation_anchor_id="anchor-a",
        occurred_at=END + timedelta(days=1),
        ingested_at=END + timedelta(days=1),
        event_kind="terminal",
        request_id="request-a",
        request_disposition="execution_intent",
        state_facts=EvidenceStateFacts(gateway_outcome="succeeded"),
    )
    source = SourceCoverage(
        "insight_event",
        availability="available",
        earliest_retained_at=prior_start,
        enumeration_complete=True,
    )
    coverage = Coverage(sources=(source,), enumeration_complete=True)
    current = inspect_operations(
        EvidenceBatch(current_ingress + (late_terminal,), snapshot, coverage), mapping
    )
    prior = inspect_operations(
        EvidenceBatch(prior_ingress, snapshot, coverage), mapping
    )
    metrics = {
        item.name: item
        for item in compute_metrics(
            current,
            prior,
            current_ingress,
            prior_ingress,
            mapping,
            Window(START, END, "ingress"),
            snapshot,
            coverage,
            coverage,
        )
    }
    operation_a = next(
        item for item in current if item.original_operation_anchor_id == "anchor-a"
    )
    assert operation_a.first_seen_at == START
    assert operation_a.last_seen_at == END + timedelta(days=1)
    assert operation_a.gateway_outcome == "succeeded"
    assert operation_a.effect_state == "unknown"
    assert metrics["requests"].count == 5
    assert metrics["requests"].unknown_count == 1
    assert metrics["requests"].excluded_count == 1
    assert metrics["active_accounts"].count == 2
    assert metrics["returning_accounts"].numerator == 1
    assert metrics["returning_accounts"].denominator == 2
    assert metrics["returning_accounts"].ratio == 0.5
    assert metrics["post_window_ingress_events"].count == 1
    assert metrics["post_window_observed_updates"].count == 1
    assert metrics["gateway.succeeded"].count == 1
    assert metrics["effect.unknown"].count == 2

    prior_gap = replace(
        coverage,
        sources=(replace(source, earliest_retained_at=START),),
    )
    partial = {
        item.name: item
        for item in compute_metrics(
            current,
            prior,
            current_ingress,
            prior_ingress,
            mapping,
            Window(START, END, "ingress"),
            snapshot,
            coverage,
            prior_gap,
        )
    }
    assert partial["requests"].completeness == "complete"
    assert partial["returning_accounts"].count == 1
    assert partial["returning_accounts"].denominator is None
    assert partial["returning_accounts"].ratio is None
    assert partial["returning_accounts"].completeness == "partial"
