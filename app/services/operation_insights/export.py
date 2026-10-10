"""Bounded, authorization-bound operator insight reports and artifacts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operation_insights.contracts import (
    AccountMapping,
    ArtifactFile,
    ArtifactManifest,
    Completeness,
    Evidence,
    EvidenceRef,
    Limits,
    Metric,
    Operation,
    Report,
    Scope,
    UnknownWalletCount,
    Window,
)


_EXCLUSIONS = ("internal", "demo", "CI", "monitoring")
_CREDENTIAL_SHAPE = re.compile(
    r"(?:\A|[^A-Za-z0-9])(?:"
    r"sk_(?:live|test)_|amw_(?:live|dev)_|github_pat_|gh[pousr]_"
    r"|xox[baprs]-|(?:AKIA|ASIA)[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_-]{12,}\.eyJ"
    r")",
    re.IGNORECASE,
)
_OPERATION_FIELDS = ("report_id",) + tuple(field.name for field in fields(Operation))
_EVIDENCE_FIELDS = ("report_id", "operation_id") + tuple(
    field.name for field in fields(Evidence)
)
_METRIC_FIELDS = ("report_id",) + tuple(field.name for field in fields(Metric))
_REPORT_FIELDS = (
    "completeness",
    "operation_count",
    "evidence_count",
    "metric_count",
) + tuple(
    field.name
    for field in fields(Report)
    if field.name not in {"operations", "evidence", "metrics"}
)


class InsightExportTimeout(Exception):
    """The bounded export could not finish before its shared deadline."""


def _assert_bound(scope: Scope, session: AsyncSession) -> None:
    from app.services.operation_insights.auth import assert_scope_bound

    assert_scope_bound(scope, session)


def _check_deadline(deadline: float | None, clock: Any) -> None:
    if deadline is not None and clock() >= deadline:
        raise InsightExportTimeout("insight_export_time_limit")


def _contains_credential_shape(value: Any) -> bool:
    if isinstance(value, str):
        return _CREDENTIAL_SHAPE.search(value) is not None
    if isinstance(value, dict):
        return any(
            _contains_credential_shape(key) or _contains_credential_shape(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_contains_credential_shape(item) for item in value)
    return False


def _validated_report(
    report: Report,
    scope: Scope,
    *,
    deadline: float | None = None,
    clock: Any = time.monotonic,
) -> Report:
    """Re-run all row, reference and provenance checks at the output boundary."""
    if not isinstance(report, Report):
        raise ValueError("invalid_insight_report")
    try:
        if len(
            report.operations
        ) > 100000 or report.window_end - report.window_start not in (
            timedelta(days=7),
            timedelta(days=30),
        ):
            raise ValueError("invalid_insight_report")

        def revalidate(value: Any) -> Any:
            _check_deadline(deadline, clock)
            if isinstance(value, type) or not is_dataclass(value):
                raise ValueError("invalid_insight_report")
            original = asdict(cast(Any, value))
            if _contains_credential_shape(original):
                raise ValueError("invalid_insight_report")
            restored = TypeAdapter(type(value)).validate_python(original, strict=False)
            if not _same_shape(original, asdict(cast(Any, restored))):
                raise ValueError("invalid_insight_report")
            return restored

        if any(
            _contains_credential_shape(getattr(report, field.name))
            for field in fields(Report)
            if field.name
            not in {
                "coverage",
                "operations",
                "evidence",
                "metrics",
                "unknown_wallet_aggregate",
            }
        ):
            raise ValueError("invalid_insight_report")
        validated = Report(
            **{
                **{field.name: getattr(report, field.name) for field in fields(Report)},
                "coverage": revalidate(report.coverage),
                "operations": tuple(revalidate(item) for item in report.operations),
                "evidence": tuple(revalidate(item) for item in report.evidence),
                "metrics": tuple(revalidate(item) for item in report.metrics),
                "unknown_wallet_aggregate": revalidate(report.unknown_wallet_aggregate),
            },
            authorized_scope=scope,
        )
        _check_deadline(deadline, clock)
        return validated
    except (TypeError, ValueError, ValidationError):
        raise ValueError("invalid_insight_report") from None


def _same_shape(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_shape(left[key], right[key]) for key in left
        )
    if isinstance(left, tuple):
        return len(left) == len(right) and all(
            _same_shape(a, b) for a, b in zip(left, right)
        )
    return bool(left == right)


def _jsonable(value: Any) -> Any:
    return TypeAdapter(type(value)).dump_python(value, mode="json")


def _report_payload(report: Report, scope: Scope) -> dict[str, Any]:
    """Pure, allowlisted projection used by tests and the streaming writer."""
    validated = _validated_report(report, scope)
    payload = TypeAdapter(Report).dump_python(validated, mode="json")
    payload.pop("authorized_scope", None)
    return payload


def _write_json(
    report: Report, output: TextIO, *, deadline: float | None, clock: Any
) -> None:
    output.write("{")
    first_field = True
    for field in sorted(fields(Report), key=lambda item: item.name):
        _check_deadline(deadline, clock)
        if not first_field:
            output.write(",")
        first_field = False
        output.write(json.dumps(field.name))
        output.write(":")
        value = getattr(report, field.name)
        if field.name in {"operations", "evidence", "metrics"}:
            output.write("[")
            for index, item in enumerate(value):
                _check_deadline(deadline, clock)
                if index:
                    output.write(",")
                output.write(
                    json.dumps(_jsonable(item), sort_keys=True, separators=(",", ":"))
                )
            output.write("]")
        else:
            output.write(
                json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
            )
    output.write("}\n")


def report_json_bytes(
    report: Report,
    *,
    scope: Scope,
    session: AsyncSession,
    deadline: float | None = None,
    clock: Any = time.monotonic,
) -> bytes:
    """Return canonical JSON only while the exact reporting scope is live."""
    _assert_bound(scope, session)
    validated = _validated_report(report, scope, deadline=deadline, clock=clock)
    output = io.StringIO()
    _write_json(validated, output, deadline=deadline, clock=clock)
    return output.getvalue().encode("utf-8")


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (tuple, list, dict)):
        text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or text.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + text
    return text


def _csv_rows(
    path: Path,
    header: tuple[str, ...],
    rows: Any,
    *,
    deadline: float | None,
    clock: Any,
) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            _check_deadline(deadline, clock)
            writer.writerow({name: _csv_cell(row.get(name)) for name in header})
            count += 1
    os.chmod(path, 0o600)
    return count


def _evidence_key(
    row: Evidence | EvidenceRef,
) -> tuple[str, str, str | None, str | None, str | None]:
    return (
        row.source,
        row.source_id,
        row.wallet_id,
        row.ownership_epoch_id,
        row.original_operation_anchor_id,
    )


def _evidence_rows(report: Report):
    linked: dict[tuple[str, str, str | None, str | None, str | None], list[str]] = {}
    for operation in report.operations:
        for ref in operation.evidence_refs:
            linked.setdefault(_evidence_key(ref), []).append(operation.operation_id)
    for evidence in report.evidence:
        row = _jsonable(evidence)
        for operation_id in linked.get(_evidence_key(evidence), [""]):
            yield {"report_id": report.report_id, "operation_id": operation_id, **row}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _completeness(report: Report) -> Completeness:
    if (
        report.coverage.enumeration_complete
        and not report.coverage.truncated
        and not report.coverage.gaps
        and not report.coverage.consistency_flags
        and not report.coverage.skew_flags
        and all(
            source.availability == "available"
            and source.enumeration_complete
            and not source.truncated
            and not source.gaps
            and not source.consistency_flags
            and not source.skew_flags
            for source in report.coverage.sources
        )
        and all(metric.completeness == "complete" for metric in report.metrics)
        and report.unknown_wallet_aggregate.status not in {"partial", "unavailable"}
    ):
        return "complete"
    return "partial"


def write_bundle(
    report: Report,
    directory: Path,
    *,
    scope: Scope,
    session: AsyncSession,
    deadline: float | None = None,
    clock: Any = time.monotonic,
) -> ArtifactManifest:
    """Atomically publish one private JSON/CSV bundle after scope validation.

    The caller supplies a new destination under its approved access and
    retention policy. This function never overwrites an existing artifact.
    """
    _assert_bound(scope, session)
    validated = _validated_report(report, scope, deadline=deadline, clock=clock)
    directory = Path(directory)
    if (
        directory.exists()
        or not directory.parent.is_dir()
        or directory.parent.is_symlink()
        or directory.parent.stat().st_mode & 0o077
    ):
        raise ValueError("insight_export_destination_unavailable")
    temporary = Path(tempfile.mkdtemp(prefix=".amw-insights-", dir=directory.parent))
    os.chmod(temporary, 0o700)
    try:
        completeness = _completeness(validated)
        file_counts: dict[str, int] = {}
        json_path = temporary / "report.json"
        with json_path.open("w", encoding="utf-8", newline="") as handle:
            _write_json(validated, handle, deadline=deadline, clock=clock)
        os.chmod(json_path, 0o600)
        file_counts["report.json"] = 1
        report_row = {
            "completeness": completeness,
            "operation_count": len(validated.operations),
            "evidence_count": len(validated.evidence),
            "metric_count": len(validated.metrics),
            **{
                field.name: _jsonable(getattr(validated, field.name))
                for field in fields(Report)
                if field.name not in {"operations", "evidence", "metrics"}
            },
        }
        file_counts["report.csv"] = _csv_rows(
            temporary / "report.csv",
            _REPORT_FIELDS,
            (report_row,),
            deadline=deadline,
            clock=clock,
        )
        file_counts["operations.csv"] = _csv_rows(
            temporary / "operations.csv",
            _OPERATION_FIELDS,
            (
                {"report_id": validated.report_id, **_jsonable(operation)}
                for operation in validated.operations
            ),
            deadline=deadline,
            clock=clock,
        )
        file_counts["evidence.csv"] = _csv_rows(
            temporary / "evidence.csv",
            _EVIDENCE_FIELDS,
            _evidence_rows(validated),
            deadline=deadline,
            clock=clock,
        )
        file_counts["aggregates.csv"] = _csv_rows(
            temporary / "aggregates.csv",
            _METRIC_FIELDS,
            (
                {"report_id": validated.report_id, **_jsonable(metric)}
                for metric in validated.metrics
            ),
            deadline=deadline,
            clock=clock,
        )
        manifest = ArtifactManifest(
            report_id=validated.report_id,
            files=tuple(
                ArtifactFile(
                    name=name,
                    sha256=_sha256(temporary / name),
                    row_count=count,
                    completeness=completeness,
                )
                for name, count in file_counts.items()
            ),
            completeness=completeness,
        )
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(_jsonable(manifest), sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_path, 0o600)
        _check_deadline(deadline, clock)
        os.rename(temporary, directory)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


async def build_report(
    scope: Scope,
    window: Window,
    limits: Limits,
    mapping: AccountMapping,
    session: AsyncSession,
    *,
    clock: Any = time.monotonic,
) -> Report:
    """Read and inspect one authorized snapshot within the shared time cap."""
    _assert_bound(scope, session)
    if window.end - window.start not in (timedelta(days=7), timedelta(days=30)):
        raise ValueError("insight_window_must_be_7_or_30_days")
    started = clock()
    deadline = started + limits.seconds
    from app.services.operation_insights.inspect import inspect_operations
    from app.services.operation_insights.sources import (
        read_evidence,
        read_unknown_wallet_count,
    )

    try:
        batch = await read_evidence(scope, window, limits, session)
    except TimeoutError:
        # No batch means no defensible snapshot or partial rows to export.
        raise InsightExportTimeout("insight_export_time_limit") from None
    timed_out = clock() >= deadline
    operations = () if timed_out else inspect_operations(batch, mapping)
    too_many = len(operations) > limits.operations
    selected = operations[: limits.operations]
    refs = {
        _evidence_key(ref) for operation in selected for ref in operation.evidence_refs
    }
    evidence = tuple(row for row in batch.rows if _evidence_key(row) in refs)
    gaps = set(batch.coverage.gaps)
    gaps.add("cohorts_not_available")
    if too_many:
        gaps.add("operation_limit_reached")
    if timed_out or clock() >= deadline:
        timed_out = True
        gaps.add("execution_budget_reached")
    coverage = replace(
        batch.coverage,
        enumeration_complete=batch.coverage.enumeration_complete
        and not (too_many or timed_out),
        truncated=batch.coverage.truncated or too_many or timed_out,
        gaps=tuple(sorted(gaps)),
    )
    unknown_count = UnknownWalletCount(status="not_authorized")
    if scope.allow_unknown_wallet_counts:
        bucket_end = window.end.replace(hour=0, minute=0, second=0, microsecond=0)
        bucket_start = bucket_end - (window.end - window.start)
        if timed_out:
            unknown_count = UnknownWalletCount(
                status="partial", bucket_start=bucket_start, bucket_end=bucket_end
            )
        else:
            try:
                unknown_count = await read_unknown_wallet_count(scope, window, session)
            except TimeoutError:
                unknown_count = UnknownWalletCount(
                    status="partial", bucket_start=bucket_start, bucket_end=bucket_end
                )
                coverage = replace(
                    coverage,
                    enumeration_complete=False,
                    truncated=True,
                    gaps=tuple(
                        sorted(set(coverage.gaps) | {"execution_budget_reached"})
                    ),
                )
    if clock() >= deadline:
        coverage = replace(
            coverage,
            enumeration_complete=False,
            truncated=True,
            gaps=tuple(sorted(set(coverage.gaps) | {"execution_budget_reached"})),
        )
    return Report(
        report_id=f"report-{uuid.uuid4().hex}",
        generated_at=datetime.now(timezone.utc),
        as_of=window.end,
        snapshot_cutoff=batch.snapshot.cutoff,
        window_start=window.start,
        window_end=window.end,
        time_basis=window.time_basis,
        environment=None,
        source_release=None,
        coverage=coverage,
        mapping_version=mapping.version,
        exclusions=_EXCLUSIONS,
        operations=selected,
        evidence=evidence,
        metrics=(),
        unknown_wallet_aggregate=unknown_count,
        authorized_scope=scope,
    )
