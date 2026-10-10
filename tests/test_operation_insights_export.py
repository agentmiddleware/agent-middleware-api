"""Operator insight artifacts are bounded, scoped, and explicit about gaps."""

from __future__ import annotations

import csv
import asyncio
import hashlib
import io
import itertools
import json
import os
import subprocess
import sys
import zipfile
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.services.operation_insights.contracts import (
    AccountMapping,
    AuthorizedOwnershipEpoch,
    Coverage,
    Evidence,
    EvidenceBatch,
    EvidenceRef,
    IngressObservation,
    Limits,
    MappingInterval,
    Operation,
    Report,
    RequestDisposition,
    Scope,
    Snapshot,
    SourceCoverage,
    Window,
)
from app.services.operation_insights.export import (
    _csv_cell,
    _report_payload,
    build_report,
    report_json_bytes,
    write_bundle,
)


UTC = timezone.utc
END = datetime(2026, 10, 10, tzinfo=UTC)
START = END - timedelta(days=7)


def _scope(*, allow_unknown: bool = False) -> Scope:
    return Scope(
        wallet_ids=frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch(
                "wallet-1", "epoch-1", START, END + timedelta(days=1)
            ),
        ),
        allow_unknown_wallet_counts=allow_unknown,
    )


def _report(count: int = 1, *, truncated: bool = False) -> Report:
    evidence = tuple(
        Evidence(
            source="audit",
            source_id=f"event-{index}",
            wallet_id="wallet-1",
            ownership_epoch_id="epoch-1",
            original_operation_anchor_id=f"anchor-{index}",
            occurred_at=START,
        )
        for index in range(count)
    )
    operations = tuple(
        Operation(
            operation_id=f"operation-{index}",
            wallet_id="wallet-1",
            ownership_epoch_id="epoch-1",
            original_operation_anchor_id=f"anchor-{index}",
            time_basis="first_observed_evidence",
            evidence_refs=(
                EvidenceRef(
                    "audit", f"event-{index}", "wallet-1", "epoch-1", f"anchor-{index}"
                ),
            ),
            first_seen_at=START,
            last_seen_at=START,
            account_id=None,
            account_class="unknown",
            mapping_status="unmapped",
        )
        for index in range(count)
    )
    return Report(
        report_id="report-1",
        generated_at=END,
        as_of=END,
        snapshot_cutoff=END,
        window_start=START,
        window_end=END,
        time_basis="first_observed_evidence",
        environment=None,
        source_release=None,
        coverage=Coverage(
            sources=(), enumeration_complete=not truncated, truncated=truncated
        ),
        mapping_version="unverified",
        exclusions=("internal", "demo", "CI", "monitoring"),
        operations=operations,
        evidence=evidence,
        metrics=(),
        authorized_scope=_scope(),
    )


def test_csv_cell_blocks_spreadsheet_formula_prefixes() -> None:
    for input_value in ("=SUM(1,1)", "+cmd", "-cmd", "@cmd", "  =SUM(1,1)", "\t=cmd"):
        assert _csv_cell(input_value).startswith("'")
    assert _csv_cell("ordinary") == "ordinary"


def test_report_projection_omits_authority_and_keeps_unknown_attribution() -> None:
    payload = _report_payload(_report(), _scope())

    assert payload["mapping_version"] == "unverified"
    assert payload["operations"][0]["mapping_status"] == "unmapped"
    assert payload["operations"][0]["account_id"] is None
    assert "authorized_scope" not in json.dumps(payload)


def test_bundle_writes_201_operations_and_checksummed_linked_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    report = _report(201)

    directory = tmp_path / "bundle"
    manifest = write_bundle(report, directory, scope=_scope(), session=object())

    assert {entry.name: entry.row_count for entry in manifest.files} == {
        "report.json": 1,
        "report.csv": 1,
        "operations.csv": 201,
        "evidence.csv": 201,
        "aggregates.csv": 0,
    }
    with (directory / "operations.csv").open(newline="", encoding="utf-8") as handle:
        operations = list(csv.DictReader(handle))
    assert operations[200]["report_id"] == "report-1"
    assert operations[200]["operation_id"] == "operation-200"
    with (directory / "evidence.csv").open(newline="", encoding="utf-8") as handle:
        evidence = list(csv.DictReader(handle))
    assert evidence[200]["operation_id"] == "operation-200"
    assert manifest.completeness == "complete"
    for item in manifest.files:
        assert (
            item.sha256
            == hashlib.sha256((directory / item.name).read_bytes()).hexdigest()
        )
    assert os.stat(directory).st_mode & 0o077 == 0


def test_partial_bundle_never_claims_exact_completion(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )

    directory = tmp_path / "bundle"
    manifest = write_bundle(
        _report(truncated=True), directory, scope=_scope(), session=object()
    )

    assert manifest.completeness == "partial"
    assert all(entry.completeness == "partial" for entry in manifest.files)
    assert (
        json.loads((directory / "report.json").read_text())["coverage"]["truncated"]
        is True
    )


def test_source_skew_marks_bundle_partial(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    report = _report()
    object.__setattr__(
        report,
        "coverage",
        Coverage(
            sources=(
                SourceCoverage(
                    source="audit",
                    availability="available",
                    enumeration_complete=True,
                    skew_flags=("clock_skew",),
                ),
            ),
            enumeration_complete=True,
        ),
    )

    manifest = write_bundle(
        report, tmp_path / "bundle", scope=_scope(), session=object()
    )
    assert manifest.completeness == "partial"


def test_mutated_walletless_evidence_is_rejected_before_json_or_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    report = _report()
    object.__setattr__(
        report, "evidence", (replace(report.evidence[0], wallet_id=None),)
    )

    with pytest.raises(ValueError, match="invalid_insight_report"):
        report_json_bytes(report, scope=_scope(), session=object())
    with pytest.raises(ValueError, match="invalid_insight_report"):
        write_bundle(report, tmp_path, scope=_scope(), session=object())
    assert tuple(tmp_path.iterdir()) == ()


def test_mutated_nested_attribution_is_rejected_without_echoing_it(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    report = _report()
    marker = "SENTINEL_DO_NOT_EXPORT"
    object.__setattr__(report.operations[0], "account_id", marker)

    with pytest.raises(ValueError, match="invalid_insight_report") as error:
        report_json_bytes(report, scope=_scope(), session=object())
    assert marker not in str(error.value)
    with pytest.raises(ValueError, match="invalid_insight_report") as bundle_error:
        write_bundle(report, tmp_path / "bundle", scope=_scope(), session=object())
    assert marker not in str(bundle_error.value)
    assert marker not in caplog.text
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize("field", ["tool", "reason_code"])
def test_credential_shaped_values_fail_closed_in_json_and_csv(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    field: str,
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    marker = "sk_live_SYNTHETIC_DO_NOT_EXPORT"
    report = _report()
    if field == "tool":
        object.__setattr__(
            report, "operations", (replace(report.operations[0], tool=marker),)
        )
    else:
        object.__setattr__(
            report, "evidence", (replace(report.evidence[0], reason_code=marker),)
        )

    with pytest.raises(ValueError, match="invalid_insight_report") as json_error:
        report_json_bytes(report, scope=_scope(), session=object())
    with pytest.raises(ValueError, match="invalid_insight_report") as csv_error:
        write_bundle(report, tmp_path / "bundle", scope=_scope(), session=object())
    assert marker not in str(json_error.value) + str(csv_error.value) + caplog.text
    assert tuple(tmp_path.iterdir()) == ()


def test_serializers_reject_oversize_and_overlong_reports_before_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    oversized = _report()
    object.__setattr__(oversized, "operations", oversized.operations * 100001)
    overlong = _report()
    object.__setattr__(overlong, "window_start", END - timedelta(days=31))

    for report in (oversized, overlong):
        with pytest.raises(ValueError, match="invalid_insight_report"):
            report_json_bytes(report, scope=_scope(), session=object())
        with pytest.raises(ValueError, match="invalid_insight_report"):
            write_bundle(report, tmp_path / "bundle", scope=_scope(), session=object())
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.asyncio
async def test_build_report_rejects_unbound_scope_before_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def deny(scope: Scope, session: object) -> None:
        calls.append("auth")
        raise ValueError("unbound")

    monkeypatch.setattr("app.services.operation_insights.auth.assert_scope_bound", deny)
    with pytest.raises(ValueError, match="unbound"):
        await build_report(
            _scope(),
            Window(START, END, "first_observed_evidence"),
            Limits(),
            AccountMapping("unverified", ()),
            object(),
        )
    assert calls == ["auth"]


@pytest.mark.asyncio
async def test_build_report_stops_at_100000_without_exact_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.operation_insights.contracts import EvidenceBatch

    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    candidate = replace(_report().operations[0], evidence_refs=())
    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence",
        lambda scope, window, limits, session: _async_value(
            EvidenceBatch(
                rows=(),
                snapshot=Snapshot(END, "snapshot-1", True, None),
                coverage=Coverage(sources=(), enumeration_complete=True),
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.operation_insights.inspect.inspect_operations",
        lambda batch, mapping: (candidate,) * 100001,
    )

    report = await build_report(
        _scope(),
        Window(START, END, "first_observed_evidence"),
        Limits(),
        AccountMapping("unverified", ()),
        object(),
    )

    assert len(report.operations) == 100000
    assert report.coverage.truncated is True
    assert report.coverage.enumeration_complete is False


@pytest.mark.parametrize("days", [7, 30])
@pytest.mark.parametrize("prior_incomplete", [False, True])
@pytest.mark.parametrize("release_conflict", [False, True])
@pytest.mark.asyncio
async def test_build_report_reconciles_current_and_prior_ingress_in_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    days: int,
    prior_incomplete: bool,
    release_conflict: bool,
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    start = END - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    scope = Scope(
        frozenset({"wallet-1"}),
        authorized_ownership_epochs=(
            AuthorizedOwnershipEpoch(
                "wallet-1", "epoch-1", previous_start, END + timedelta(days=1)
            ),
        ),
    )
    mapping = AccountMapping(
        "verified-1",
        (MappingInterval("wallet-1", "account-1", "eligible", previous_start, None),),
    )
    current_at = start + timedelta(days=1)
    prior_at = start - timedelta(days=1)

    def ingress(label: str, at: datetime, disposition: RequestDisposition) -> Evidence:
        return Evidence(
            source="insight_event",
            source_id=f"evt-{label}",
            wallet_id="wallet-1",
            ownership_epoch_id="epoch-1",
            original_operation_anchor_id=f"anchor-{label}",
            request_id=f"request-{label}",
            occurred_at=at,
            event_kind="ingress",
            request_disposition=disposition,
            environment="staging",
            server_release=(
                "release-b" if release_conflict and label == "status" else "release-a"
            ),
        )

    current = ingress("current", current_at, "execution_intent")
    status = ingress("status", current_at, "non_execution_read")
    prior = ingress("prior", prior_at, "execution_intent")
    coverage = Coverage(
        sources=(
            SourceCoverage(
                "insight_event",
                availability="available",
                earliest_retained_at=previous_start,
                enumeration_complete=True,
            ),
        ),
        enumeration_complete=True,
    )
    earlier_coverage = (
        Coverage(
            sources=(replace(coverage.sources[0], earliest_retained_at=start),),
            enumeration_complete=False,
            gaps=("retention_unverified",),
        )
        if prior_incomplete
        else coverage
    )
    calls: list[Window] = []

    async def read_batch(scope, window, limits, session) -> EvidenceBatch:
        calls.append(window)
        earlier = window.end == start
        events = (prior,) if earlier else (current, status)
        return EvidenceBatch(
            rows=(prior,) if earlier else (current,),
            snapshot=Snapshot(END, "same-transaction", True, None),
            coverage=earlier_coverage if earlier else coverage,
            window_ingress=events,
        )

    def inspect(batch: EvidenceBatch, mapping: AccountMapping) -> tuple[Operation, ...]:
        event = next(
            row for row in batch.rows if row.request_disposition == "execution_intent"
        )
        return (
            Operation(
                operation_id=f"operation-{event.source_id}",
                wallet_id="wallet-1",
                time_basis="ingress",
                ownership_epoch_id="epoch-1",
                original_operation_anchor_id=event.original_operation_anchor_id,
                first_seen_at=event.occurred_at,
                execution_intent=True,
                environment="staging",
                server_release="release-a",
                ingress_observations=(
                    IngressObservation(
                        event.request_id, event.occurred_at, "execution_intent"
                    ),
                ),
                evidence_refs=(
                    EvidenceRef(
                        event.source,
                        event.source_id,
                        event.wallet_id,
                        event.ownership_epoch_id,
                        event.original_operation_anchor_id,
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence", read_batch
    )
    monkeypatch.setattr(
        "app.services.operation_insights.inspect.inspect_operations", inspect
    )

    report = await build_report(
        scope, Window(start, END, "ingress"), Limits(), mapping, object()
    )

    metrics = {metric.name: metric for metric in report.metrics}
    assert [(window.start, window.end) for window in calls] == [
        (start, END),
        (previous_start, start),
    ]
    assert metrics["requests"].count == 2
    assert metrics["requests"].completeness == "complete"
    assert metrics["active_accounts"].count == 1
    assert metrics["returning_accounts"].numerator == 1
    assert metrics["returning_accounts"].denominator == (
        None if prior_incomplete else 1
    )
    assert metrics["returning_accounts"].completeness == (
        "partial" if prior_incomplete else "complete"
    )
    assert (
        "prior_window_retention_incomplete" in report.coverage.gaps
    ) == prior_incomplete
    assert {row.source_id for row in report.evidence} == {"evt-current", "evt-status"}
    assert report.coverage.enumeration_complete is not prior_incomplete
    assert report.environment == "staging"
    assert report.source_release == (None if release_conflict else "release-a")
    payload = _report_payload(report, scope)
    assert payload["environment"] == "staging"
    assert payload["source_release"] == (None if release_conflict else "release-a")
    directory = tmp_path / "bundle"
    manifest = write_bundle(report, directory, scope=scope, session=object())
    with (directory / "report.csv").open(newline="", encoding="utf-8") as handle:
        report_row = next(csv.DictReader(handle))
    assert report_row["environment"] == "staging"
    assert report_row["source_release"] == ("" if release_conflict else "release-a")
    assert json.loads((directory / "report.json").read_text())["source_release"] == (
        None if release_conflict else "release-a"
    )
    assert manifest.completeness == ("partial" if prior_incomplete else "complete")


@pytest.mark.asyncio
async def test_build_report_marks_budget_expiry_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.operation_insights.contracts import EvidenceBatch

    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence",
        lambda scope, window, limits, session: _async_value(
            EvidenceBatch(
                rows=(),
                snapshot=Snapshot(END, "snapshot-1", True, None),
                coverage=Coverage(sources=(), enumeration_complete=True),
            )
        ),
    )
    ticks = itertools.chain((0.0,), itertools.repeat(301.0))

    report = await build_report(
        _scope(),
        Window(START, END, "first_observed_evidence"),
        Limits(),
        AccountMapping("unverified", ()),
        object(),
        clock=lambda: next(ticks),
    )

    assert report.operations == ()
    assert report.coverage.truncated is True
    assert "execution_budget_reached" in report.coverage.gaps


@pytest.mark.parametrize("gap", ["execution_budget_reached", "evidence_limit_reached"])
@pytest.mark.asyncio
async def test_build_report_preserves_rows_from_budgeted_reader(
    tmp_path, monkeypatch: pytest.MonkeyPatch, gap: str
) -> None:
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    root = Evidence(
        source="idempotency",
        source_id="budget-root",
        wallet_id="wallet-1",
        ownership_epoch_id="epoch-1",
        original_operation_anchor_id="budget-root",
        logical_operation_id="budget-root",
        occurred_at=START + timedelta(days=1),
    )
    read_limits: list[int] = []

    async def partial_batch(scope, window, limits, session):
        read_limits.append(limits.seconds)
        assert len(read_limits) == 1  # No prior read after current read budget expires.
        return EvidenceBatch(
            rows=(root,),
            snapshot=Snapshot(END, "snapshot-budget", True, None),
            coverage=Coverage(
                sources=(),
                truncated=True,
                gaps=(gap,),
            ),
        )

    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence", partial_batch
    )
    ticks = itertools.chain((0.0,), itertools.repeat(200.0))
    scope = _scope()
    report = await build_report(
        scope,
        Window(START, END, "first_observed_evidence"),
        Limits(),
        AccountMapping("unverified", ()),
        object(),
        clock=lambda: next(ticks),
    )

    assert read_limits == [200]
    assert len(report.operations) == 1
    assert report.operations[0].operation_id
    assert report.coverage.truncated is True
    assert gap in report.coverage.gaps
    assert "prior_window_skipped_current_partial" in report.coverage.gaps
    assert all(metric.completeness == "partial" for metric in report.metrics)
    assert all(metric.ratio is None for metric in report.metrics)
    directory = tmp_path / "bundle"
    manifest = write_bundle(
        report,
        directory,
        scope=scope,
        session=object(),
        deadline=300.0,
        clock=lambda: 200.0,
    )
    assert manifest.completeness == "partial"
    assert manifest.files[0].row_count == 1


@pytest.mark.asyncio
async def test_authorized_unknown_count_timeout_is_partial_not_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.operation_insights.contracts import EvidenceBatch

    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence",
        lambda scope, window, limits, session: _async_value(
            EvidenceBatch(
                rows=(),
                snapshot=Snapshot(END, "snapshot-1", True, None),
                coverage=Coverage(sources=(), enumeration_complete=True),
            )
        ),
    )
    ticks = itertools.chain((0.0,), itertools.repeat(301.0))

    report = await build_report(
        _scope(allow_unknown=True),
        Window(START, END, "first_observed_evidence"),
        Limits(),
        AccountMapping("unverified", ()),
        object(),
        clock=lambda: next(ticks),
    )

    assert report.unknown_wallet_aggregate.status == "partial"
    assert report.unknown_wallet_aggregate.count is None
    assert report.unknown_wallet_aggregate.bucket_start == START
    assert report.unknown_wallet_aggregate.bucket_end == END


@pytest.mark.asyncio
async def test_reader_timeout_emits_no_report_or_artifact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.operation_insights.export import InsightExportTimeout

    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )

    async def timed_out(*args):
        raise TimeoutError("insight_read_budget_exceeded")

    monkeypatch.setattr(
        "app.services.operation_insights.sources.read_evidence", timed_out
    )

    with pytest.raises(InsightExportTimeout, match="insight_export_time_limit"):
        await build_report(
            _scope(),
            Window(START, END, "first_observed_evidence"),
            Limits(),
            AccountMapping("unverified", ()),
            object(),
        )
    assert tuple(tmp_path.iterdir()) == ()


async def _async_value(value):
    return value


def test_operator_report_http_route_requires_reporting_bearer() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers.operation_insights import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(
            "/v1/operator/insights/report",
            params={
                "wallet_id": "wallet-1",
                "as_of": END.isoformat(),
                "days": 7,
                "time_basis": "first_observed_evidence",
            },
        )
    assert response.status_code == 401


@pytest.mark.parametrize("enabled", [False, True])
def test_application_mounts_reporting_only_when_enabled(enabled: bool) -> None:
    environment = {
        **os.environ,
        "OPERATION_INSIGHTS_REPORTING_ENABLED": str(enabled).lower(),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.main import app; "
            "print('/v1/operator/insights/report' in app.openapi()['paths'])",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(enabled)


@pytest.mark.asyncio
async def test_operation_authorizes_wallet_before_looking_up_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from app.core.oidc_iga import EnterprisePrincipal
    from app.routers import operation_insights as route

    calls: list[str] = []

    @asynccontextmanager
    async def transaction(session):
        yield session

    async def denied(*args):
        calls.append("authorize")
        raise HTTPException(status_code=403, detail="insight_scope_denied")

    async def must_not_read(*args, **kwargs):
        calls.append("read")
        raise AssertionError("lookup happened before authorization")

    monkeypatch.setattr(route, "reporting_read_transaction", transaction)
    monkeypatch.setattr(route, "authorize_scope", denied)
    monkeypatch.setattr(route, "build_report", must_not_read)
    principal = EnterprisePrincipal("subject-1", "okta", "https://issuer.example")

    with pytest.raises(HTTPException) as error:
        await route.get_operation_insight(
            operation_id="hidden-id",
            wallet_id="wallet-foreign",
            as_of=END,
            days=7,
            time_basis="first_observed_evidence",
            principal=principal,
            session=object(),
        )
    assert error.value.status_code == 403
    assert calls == ["authorize"]


@pytest.mark.asyncio
@pytest.mark.parametrize("format", ["json", "csv"])
async def test_operator_route_delivers_only_prepared_scoped_artifact(
    monkeypatch: pytest.MonkeyPatch, format: str
) -> None:
    from app.core.oidc_iga import EnterprisePrincipal
    from app.routers import operation_insights as route

    @asynccontextmanager
    async def transaction(session):
        yield session

    async def authorize(*args):
        return _scope()

    async def prepared_report(*args, **kwargs):
        assert isinstance(kwargs["deadline"], float)
        return _report()

    monkeypatch.setattr(route, "reporting_read_transaction", transaction)
    monkeypatch.setattr(route, "authorize_scope", authorize)
    monkeypatch.setattr(route, "build_report", prepared_report)
    monkeypatch.setattr(
        "app.services.operation_insights.auth.assert_scope_bound",
        lambda scope, session: None,
    )
    principal = EnterprisePrincipal("subject-1", "okta", "https://issuer.example")

    response = await route.get_insight_report(
        wallet_ids=["wallet-1"],
        as_of=END,
        days=7,
        time_basis="first_observed_evidence",
        principal=principal,
        session=object(),
        format=format,
    )

    assert response.headers["Cache-Control"] == "no-store"
    if format == "json":
        assert json.loads(response.body)["report_id"] == "report-1"
    else:
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            assert set(archive.namelist()) == {
                "report.json",
                "report.csv",
                "operations.csv",
                "evidence.csv",
                "aggregates.csv",
                "manifest.json",
            }
            assert json.loads(archive.read("manifest.json"))["report_id"] == "report-1"


@pytest.mark.asyncio
async def test_operator_route_cuts_off_slow_authorization_before_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from app.core.oidc_iga import EnterprisePrincipal
    from app.routers import operation_insights as route

    calls: list[str] = []

    @asynccontextmanager
    async def transaction(session):
        yield session

    async def slow_authorize(*args):
        await asyncio.sleep(0.01)
        calls.append("authorized")
        return _scope()

    async def must_not_read(*args):
        calls.append("read")
        raise AssertionError("reader ran after deadline")

    monkeypatch.setattr(route, "reporting_read_transaction", transaction)
    monkeypatch.setattr(route, "authorize_scope", slow_authorize)
    monkeypatch.setattr(route, "build_report", must_not_read)
    monkeypatch.setattr(
        route, "_request_deadline", lambda limits: asyncio.get_running_loop().time() - 1
    )
    principal = EnterprisePrincipal("subject-1", "okta", "https://issuer.example")

    with pytest.raises(HTTPException) as error:
        await route.get_insight_report(
            wallet_ids=["wallet-1"],
            as_of=END,
            days=7,
            time_basis="first_observed_evidence",
            principal=principal,
            session=object(),
            format="json",
        )
    assert error.value.status_code == 503
    assert calls == []


def test_insight_cli_never_falls_through_to_bootstrap(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import operator_analytics_export as cli

    monkeypatch.delenv("AMW_INSIGHTS_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "operator_analytics_export.py",
            "--insights",
            "--api-url",
            "https://example.test",
            "--wallet-id",
            "wallet-1",
            "--as-of",
            END.isoformat(),
            "--days",
            "7",
            "--time-basis",
            "first_observed_evidence",
            "--out",
            str(tmp_path / "report.json"),
        ],
    )
    monkeypatch.setattr(
        cli,
        "_bootstrap_key",
        lambda value: (_ for _ in ()).throw(
            AssertionError("bootstrap called on insight path")
        ),
    )

    with pytest.raises(SystemExit, match="AMW_INSIGHTS_BEARER_TOKEN"):
        cli.main()
    assert tuple(tmp_path.iterdir()) == ()


def test_insight_cli_uses_only_bearer_and_writes_private_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from scripts import operator_analytics_export as cli

    observed: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"report_id": "report-1"})

    client_type = httpx.Client
    monkeypatch.setattr(
        cli.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setenv("AMW_INSIGHTS_BEARER_TOKEN", "synthetic-token")
    output = tmp_path / "report.json"

    cli.export_insights(
        api_url="https://example.test",
        wallet_ids=("wallet-1",),
        as_of=END.isoformat(),
        days=7,
        time_basis="first_observed_evidence",
        output=output,
        format="json",
        include_unknown_wallet_counts=False,
    )

    assert json.loads(output.read_text())["report_id"] == "report-1"
    assert os.stat(output).st_mode & 0o077 == 0
    assert len(observed) == 1
    assert observed[0].headers["Authorization"] == "Bearer synthetic-token"
    assert "X-API-Key" not in observed[0].headers


def test_insight_cli_error_does_not_echo_response_body(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from scripts import operator_analytics_export as cli

    marker = "SENTINEL_DO_NOT_ECHO"
    client_type = httpx.Client
    monkeypatch.setattr(
        cli.httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, text=marker)
            ),
            **kwargs,
        ),
    )
    monkeypatch.setenv("AMW_INSIGHTS_BEARER_TOKEN", "synthetic-token")
    output = tmp_path / "report.json"

    with pytest.raises(
        SystemExit, match="insight report request returned 503"
    ) as error:
        cli.export_insights(
            api_url="https://example.test",
            wallet_ids=("wallet-1",),
            as_of=END.isoformat(),
            days=7,
            time_basis="first_observed_evidence",
            output=output,
            format="json",
            include_unknown_wallet_counts=False,
        )
    assert marker not in str(error.value)
    assert not output.exists()
