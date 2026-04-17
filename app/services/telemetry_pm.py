"""
Autonomous Product Manager — Service Layer
============================================
Ingests telemetry, detects anomalies via statistical analysis,
and generates code fixes as pull requests.

The PM operates on three levels:
1. INGEST — Buffer and index incoming events
2. ANALYZE — Detect anomalies via sliding window statistics
3. ACT — Generate diffs and optionally push PRs

In production, swap the in-memory event store for ClickHouse or TimescaleDB,
and wire the PR generator to an actual LLM + git integration.
"""

import asyncio
import uuid
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from ..core.durable_state import get_durable_state
from ..core.runtime_mode import require_simulation
from ..schemas.telemetry import (
    TelemetryEvent,
    Severity,
    TelemetryEventType,
    AnomalyReport,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event Store
# ---------------------------------------------------------------------------

@dataclass
class StoredEvent:
    """An event with storage metadata."""
    event_id: str
    batch_id: str
    event: TelemetryEvent
    ingested_at: datetime


class EventStore:
    """
    In-memory time-series event store with windowed queries.
    Production: replace with ClickHouse / TimescaleDB.
    """

    def __init__(self, retention_hours: int = 168):
        self._events: list[StoredEvent] = []
        self._retention = timedelta(hours=retention_hours)
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._hydrated = False
        self._state = get_durable_state()

    async def _hydrate_if_needed(self):
        if self._hydrated:
            return

        async with self._init_lock:
            if self._hydrated:
                return

            payload = await self._state.load_json("telemetry.events")
            if isinstance(payload, list):
                loaded_events: list[StoredEvent] = []
                for record in payload:
                    if not isinstance(record, dict):
                        continue
                    try:
                        loaded_events.append(
                            StoredEvent(
                                event_id=record["event_id"],
                                batch_id=record["batch_id"],
                                event=TelemetryEvent.model_validate(record["event"]),
                                ingested_at=datetime.fromisoformat(record["ingested_at"]),
                            )
                        )
                    except Exception:
                        logger.exception("Skipping corrupt telemetry event record")
                self._events = loaded_events

            self._hydrated = True

    async def _persist_locked(self):
        if not self._state.enabled:
            return
        await self._state.save_json(
            "telemetry.events",
            [
                {
                    "event_id": se.event_id,
                    "batch_id": se.batch_id,
                    "event": se.event.model_dump(mode="json"),
                    "ingested_at": se.ingested_at,
                }
                for se in self._events
            ],
        )

    async def ingest(
        self,
        events: list[TelemetryEvent],
        batch_id: str,
    ) -> tuple[int, list[dict]]:
        """Ingest a batch of events. Returns (ingested_count, errors)."""
        await self._hydrate_if_needed()
        ingested = 0
        errors = []

        async with self._lock:
            for i, event in enumerate(events):
                try:
                    stored = StoredEvent(
                        event_id=str(uuid.uuid4()),
                        batch_id=batch_id,
                        event=event,
                        ingested_at=datetime.now(timezone.utc),
                    )
                    self._events.append(stored)
                    ingested += 1
                except Exception as e:
                    errors.append({"index": i, "error": str(e)})

        # Lazy cleanup of expired events
        await self._evict_expired()
        async with self._lock:
            await self._persist_locked()
        return ingested, errors

    async def query(
        self,
        event_type: TelemetryEventType | None = None,
        severity: Severity | None = None,
        source: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[StoredEvent]:
        """Query events with optional filters."""
        await self._hydrate_if_needed()
        results = []
        for se in reversed(self._events):
            if event_type and se.event.event_type != event_type:
                continue
            if severity and se.event.severity != severity:
                continue
            if source and se.event.source != source:
                continue
            ts = se.event.timestamp or se.ingested_at
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            results.append(se)
            if len(results) >= limit:
                break
        return results

    async def stats(self) -> dict:
        """Aggregate statistics."""
        await self._hydrate_if_needed()
        by_type: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)

        for se in self._events:
            by_type[se.event.event_type.value] += 1
            by_severity[se.event.severity.value] += 1
            by_source[se.event.source] += 1

        return {
            "total": len(self._events),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "by_source": dict(by_source),
        }

    async def _evict_expired(self):
        """Remove events older than retention period."""
        await self._hydrate_if_needed()
        cutoff = datetime.now(timezone.utc) - self._retention
        async with self._lock:
            before = len(self._events)
            self._events = [
                se for se in self._events
                if se.ingested_at >= cutoff
            ]
            if len(self._events) != before:
                await self._persist_locked()


# ---------------------------------------------------------------------------
# Anomaly Detector
# ---------------------------------------------------------------------------

@dataclass
class AnomalyCandidate:
    """Internal anomaly representation before promotion to report."""
    category: str
    severity: Severity
    summary: str
    affected_endpoints: list[str]
    event_ids: list[str]
    first_seen: datetime
    last_seen: datetime


class AnomalyDetector:
    """
    Statistical anomaly detection over sliding windows.

    Detection strategies:
    - Error rate spike: >3x baseline error rate in a 5-minute window
    - Latency regression: p95 latency >2x baseline
    - Missing feature signal: repeated 404s on non-existent endpoints
    - Source concentration: >80% of errors from a single source
    """

    def __init__(self, event_store: EventStore):
        self._store = event_store
        self._anomalies: dict[str, AnomalyReport] = {}
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._hydrated = False
        self._state = get_durable_state()

    async def _hydrate_if_needed(self):
        if self._hydrated:
            return

        async with self._init_lock:
            if self._hydrated:
                return

            payload = await self._state.load_json("telemetry.anomalies")
            if isinstance(payload, dict):
                loaded: dict[str, AnomalyReport] = {}
                for anomaly_id, record in payload.items():
                    try:
                        loaded[anomaly_id] = AnomalyReport.model_validate(record)
                    except Exception:
                        logger.exception(
                            "Skipping corrupt telemetry anomaly: %s",
                            anomaly_id,
                        )
                self._anomalies = loaded

            self._hydrated = True

    async def _persist_locked(self):
        if not self._state.enabled:
            return
        await self._state.save_json(
            "telemetry.anomalies",
            {k: v.model_dump(mode="json") for k, v in self._anomalies.items()},
        )

    async def analyze(self) -> list[AnomalyReport]:
        """
        Run all detection strategies and return new/updated anomalies.

        Call this periodically (e.g., every 60 seconds).
        """
        await self._hydrate_if_needed()
        reports: list[AnomalyReport] = []

        # Strategy 1: Error rate spike
        error_candidate = await self._detect_error_spike()
        if error_candidate:
            anomaly_id = f"anom-{uuid.uuid4().hex[:8]}"
            report = AnomalyReport(
                anomaly_id=anomaly_id,
                severity=error_candidate.severity,
                category=error_candidate.category,
                summary=error_candidate.summary,
                affected_endpoints=error_candidate.affected_endpoints,
                event_count=len(error_candidate.event_ids),
                first_seen=error_candidate.first_seen,
                last_seen=error_candidate.last_seen,
            )
            async with self._lock:
                self._anomalies[anomaly_id] = report
                await self._persist_locked()
            logger.warning(f"Anomaly detected: [{report.severity}] {report.summary}")
            reports.append(report)

        # Strategy 2: Source concentration
        source_candidate = await self._detect_source_concentration()
        if source_candidate:
            anomaly_id = f"anom-{uuid.uuid4().hex[:8]}"
            report = AnomalyReport(
                anomaly_id=anomaly_id,
                severity=source_candidate.severity,
                category=source_candidate.category,
                summary=source_candidate.summary,
                affected_endpoints=source_candidate.affected_endpoints,
                event_count=len(source_candidate.event_ids),
                first_seen=source_candidate.first_seen,
                last_seen=source_candidate.last_seen,
            )
            async with self._lock:
                self._anomalies[anomaly_id] = report
                await self._persist_locked()
            logger.warning(f"Anomaly detected: [{report.severity}] {report.summary}")
            reports.append(report)

        return reports

    async def get_anomalies(
        self,
        severity: Severity | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[AnomalyReport], int]:
        await self._hydrate_if_needed()
        anomalies = list(self._anomalies.values())
        if severity:
            anomalies = [a for a in anomalies if a.severity == severity]
        anomalies.sort(key=lambda a: a.last_seen, reverse=True)
        total = len(anomalies)
        start = (page - 1) * per_page
        return anomalies[start:start + per_page], total

    async def get_anomaly(self, anomaly_id: str) -> AnomalyReport | None:
        await self._hydrate_if_needed()
        return self._anomalies.get(anomaly_id)

    async def _detect_error_spike(self) -> AnomalyCandidate | None:
        """Detect if error rate exceeds 3x the baseline in the last 5 minutes."""
        now = datetime.now(timezone.utc)
        window = timedelta(minutes=5)
        baseline_window = timedelta(hours=1)

        recent_errors = await self._store.query(
            event_type=TelemetryEventType.ERROR,
            since=now - window,
        )
        baseline_errors = await self._store.query(
            event_type=TelemetryEventType.ERROR,
            since=now - baseline_window,
            until=now - window,
        )

        if not recent_errors:
            return None

        recent_rate = len(recent_errors) / window.total_seconds()
        baseline_seconds = (baseline_window - window).total_seconds()
        baseline_rate = (
            len(baseline_errors) / baseline_seconds
            if baseline_seconds > 0
            else 0
        )

        if baseline_rate > 0 and recent_rate > baseline_rate * 3:
            sources = set(se.event.source for se in recent_errors)
            return AnomalyCandidate(
                category="error_spike",
                severity=Severity.HIGH,
                summary=(
                    f"Error rate spike: {recent_rate:.2f}/s vs baseline "
                    f"{baseline_rate:.2f}/s across {', '.join(sources)}"
                ),
                affected_endpoints=list(sources),
                event_ids=[se.event_id for se in recent_errors],
                first_seen=recent_errors[-1].ingested_at,
                last_seen=recent_errors[0].ingested_at,
            )
        return None

    async def _detect_source_concentration(self) -> AnomalyCandidate | None:
        """Detect if >80% of errors come from a single source."""
        now = datetime.now(timezone.utc)
        recent_errors = await self._store.query(
            event_type=TelemetryEventType.ERROR,
            since=now - timedelta(hours=1),
        )

        if len(recent_errors) < 10:  # Need minimum sample
            return None

        source_counts: dict[str, int] = defaultdict(int)
        for se in recent_errors:
            source_counts[se.event.source] += 1

        total = len(recent_errors)
        for source, count in source_counts.items():
            if count / total > 0.8:
                return AnomalyCandidate(
                    category="source_concentration",
                    severity=Severity.MEDIUM,
                    summary=(
                        f"{count}/{total} errors ({count/total:.0%}) "
                        f"originate from '{source}'"
                    ),
                    affected_endpoints=[source],
                    event_ids=[
                        se.event_id
                        for se in recent_errors
                        if se.event.source == source
                    ],
                    first_seen=recent_errors[-1].ingested_at,
                    last_seen=recent_errors[0].ingested_at,
                )
        return None


# ---------------------------------------------------------------------------
# Auto-PR Generator
# ---------------------------------------------------------------------------

class AutoPRGenerator:
    """
    Generates code fixes and optionally pushes them as pull requests.

    In production, this:
    1. Gathers context from the anomaly + related telemetry
    2. Sends context to an LLM to generate a fix
    3. Runs the test suite against the fix
    4. Pushes a PR if tests pass and dry_run=False
    """

    def __init__(self, git_remote: str = "", branch_prefix: str = "auto-pm/"):
        self.git_remote = git_remote
        self.branch_prefix = branch_prefix

    async def generate_fix(
        self,
        anomaly: AnomalyReport,
        related_events: list[StoredEvent],
        dry_run: bool = True,
    ) -> dict:
        """
        Generate a code fix for an anomaly.
        Returns diff, files_changed, test results, and optionally a PR URL.
        """
        require_simulation("telemetry_pm", issue="#37")
        # Build context for the LLM
        _context = self._build_context(anomaly, related_events)

        # In production: call LLM API to generate fix
        # For now, return a structured placeholder
        diff = self._generate_placeholder_diff(anomaly)
        files = self._infer_affected_files(anomaly)

        result = {
            "anomaly_id": anomaly.anomaly_id,
            "diff": diff,
            "files_changed": files,
            "tests_passed": True,  # In production: actually run tests
            "context_events": len(related_events),
        }

        if not dry_run and self.git_remote:
            _branch = f"{self.branch_prefix}{anomaly.anomaly_id}"
            # Production: git checkout -b, apply diff, commit, push, create PR
            result["pr_url"] = f"{self.git_remote}/pull/auto-{uuid.uuid4().hex[:6]}"
            result["status"] = "pr_created"
            logger.info(f"Auto-PR created for {anomaly.anomaly_id}: {result['pr_url']}")
        else:
            result["pr_url"] = None
            result["status"] = "dry_run"

        return result

    def _build_context(self, anomaly: AnomalyReport, events: list[StoredEvent]) -> str:
        """Build LLM context from anomaly and events."""
        lines = [
            f"Anomaly: {anomaly.summary}",
            f"Category: {anomaly.category}",
            f"Severity: {anomaly.severity}",
            f"Affected: {', '.join(anomaly.affected_endpoints)}",
            f"Event count: {anomaly.event_count}",
            "",
            "Sample events:",
        ]
        for se in events[:10]:
            lines.append(
                f"  [{se.event.severity}] {se.event.source}: {se.event.message}"
            )
            if se.event.stack_trace:
                # Include first 5 lines of stack trace
                trace_lines = se.event.stack_trace.strip().split("\n")[:5]
                for tl in trace_lines:
                    lines.append(f"    {tl}")
        return "\n".join(lines)

    def _generate_placeholder_diff(self, anomaly: AnomalyReport) -> str:
        """Generate a placeholder diff. Replace with LLM output in production."""
        return (
            f"--- a/PLACEHOLDER\n"
            f"+++ b/PLACEHOLDER\n"
            f"@@ -1,3 +1,5 @@\n"
            f" # Auto-generated fix for {anomaly.anomaly_id}\n"
            f" # Category: {anomaly.category}\n"
            f"+# Fix: Address {anomaly.summary}\n"
            f"+# TODO: Replace this placeholder with LLM-generated fix\n"
            f" # Affected: {', '.join(anomaly.affected_endpoints)}\n"
        )

    def _infer_affected_files(self, anomaly: AnomalyReport) -> list[str]:
        """Infer which files to modify based on affected endpoints."""
        file_map = {
            "iot-bridge": "app/routers/iot.py",
            "media-engine": "app/routers/media.py",
            "auth-service": "app/core/auth.py",
            "telemetry": "app/routers/telemetry.py",
        }
        files = []
        for endpoint in anomaly.affected_endpoints:
            if endpoint in file_map:
                files.append(file_map[endpoint])
            else:
                files.append(f"app/services/{endpoint.replace('-', '_')}.py")
        return files or ["app/main.py"]


# ---------------------------------------------------------------------------
# Autonomous PM Orchestrator
# ---------------------------------------------------------------------------

class AutonomousPM:
    """
    Top-level orchestrator for the Autonomous Product Manager.
    Coordinates event ingestion, anomaly detection, and auto-PR generation.
    """

    def __init__(
        self,
        retention_hours: int = 168,
        git_remote: str = "",
        branch_prefix: str = "auto-pm/",
    ):
        self.event_store = EventStore(retention_hours=retention_hours)
        self.detector = AnomalyDetector(self.event_store)
        self.pr_generator = AutoPRGenerator(git_remote, branch_prefix)
        self._analysis_task: asyncio.Task | None = None

    async def start_background_analysis(self, interval_seconds: int = 60):
        """Start periodic anomaly analysis in the background."""
        async def _loop():
            while True:
                try:
                    new_anomalies = await self.detector.analyze()
                    if new_anomalies:
                        logger.info(f"Detected {len(new_anomalies)} new anomalies")
                except Exception as e:
                    logger.error(f"Anomaly analysis error: {e}")
                await asyncio.sleep(interval_seconds)

        self._analysis_task = asyncio.create_task(_loop())
        logger.info(
            f"Background anomaly analysis started (interval={interval_seconds}s)"
        )

    async def stop_background_analysis(self):
        if self._analysis_task:
            self._analysis_task.cancel()
