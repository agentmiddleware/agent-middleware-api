"""
Direct tests for the PG-backed EventStore introduced in #28.

test_telemetry.py already covers the HTTP surface. These tests exercise
the store in isolation to verify: round-trip fidelity, filter correctness,
retention eviction, and stats aggregation.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models import TelemetryEventModel
from app.db.database import get_session_factory
from app.schemas.telemetry import (
    Severity,
    TelemetryEvent,
    TelemetryEventType,
)
from app.services.telemetry_pm import EventStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(autouse=True)
async def _clean_telemetry_table():
    """Per-test isolation — other tests may have written events."""
    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import delete

        await session.execute(delete(TelemetryEventModel))
        await session.commit()
    yield


def _event(
    event_type: TelemetryEventType = TelemetryEventType.ERROR,
    severity: Severity = Severity.HIGH,
    source: str = "iot-bridge",
    message: str = "boom",
    metadata: dict | None = None,
    timestamp: datetime | None = None,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_type=event_type,
        severity=severity,
        source=source,
        message=message,
        metadata=metadata or {},
        timestamp=timestamp,
    )


@pytest.mark.anyio
async def test_ingest_then_query_round_trip():
    """What goes in must come out with fields intact."""
    store = EventStore(retention_hours=168)

    events = [
        _event(message="first", metadata={"k": "v1"}),
        _event(severity=Severity.LOW, message="second", metadata={"k": "v2"}),
    ]
    count, errors = await store.ingest(events, batch_id="b-roundtrip")

    assert count == 2
    assert errors == []

    fetched = await store.query()
    assert len(fetched) == 2
    # Ordered newest-first → second was inserted second, appears first.
    messages = [se.event.message for se in fetched]
    assert set(messages) == {"first", "second"}

    for se in fetched:
        assert se.batch_id == "b-roundtrip"
        assert se.event.metadata.get("k") in {"v1", "v2"}


@pytest.mark.anyio
async def test_query_filters():
    store = EventStore()

    await store.ingest(
        [
            _event(event_type=TelemetryEventType.ERROR, severity=Severity.HIGH, source="a"),
            _event(event_type=TelemetryEventType.WARNING, severity=Severity.MEDIUM, source="a"),
            _event(event_type=TelemetryEventType.ERROR, severity=Severity.HIGH, source="b"),
        ],
        batch_id="b-filters",
    )

    # by event_type
    errors_only = await store.query(event_type=TelemetryEventType.ERROR)
    assert len(errors_only) == 2
    assert all(se.event.event_type == TelemetryEventType.ERROR for se in errors_only)

    # by severity
    high_only = await store.query(severity=Severity.HIGH)
    assert len(high_only) == 2

    # by source
    a_only = await store.query(source="a")
    assert len(a_only) == 2
    assert all(se.event.source == "a" for se in a_only)

    # combined filter
    errors_from_a = await store.query(event_type=TelemetryEventType.ERROR, source="a")
    assert len(errors_from_a) == 1


@pytest.mark.anyio
async def test_stats_aggregation():
    store = EventStore()

    await store.ingest(
        [
            _event(event_type=TelemetryEventType.ERROR, source="svc-a"),
            _event(event_type=TelemetryEventType.ERROR, source="svc-b"),
            _event(event_type=TelemetryEventType.WARNING, severity=Severity.MEDIUM, source="svc-a"),
        ],
        batch_id="b-stats",
    )

    stats = await store.stats()
    assert stats["total"] == 3
    assert stats["by_type"]["error"] == 2
    assert stats["by_type"]["warning"] == 1
    assert stats["by_source"]["svc-a"] == 2
    assert stats["by_source"]["svc-b"] == 1


@pytest.mark.anyio
async def test_evict_expired_drops_old_rows():
    """Anything older than the retention window must be purged."""
    # Retention = 1 hour. We'll manually insert a row with a past ingested_at.
    store = EventStore(retention_hours=1)

    # Ingest a fresh event first so there's a known baseline.
    await store.ingest([_event(message="fresh")], batch_id="b-fresh")

    # Manually insert an expired row (2 hours old).
    factory = get_session_factory()
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    async with factory() as session:
        session.add(
            TelemetryEventModel(
                event_id="expired-evt",
                batch_id="b-old",
                event_type="error",
                severity="high",
                source="ghost",
                message="old",
                ingested_at=two_hours_ago,
            )
        )
        await session.commit()

    # Sanity: both rows are queryable before eviction.
    pre = await store.query(limit=100)
    assert len(pre) == 2

    removed = await store._evict_expired()
    assert removed == 1

    post = await store.query(limit=100)
    assert len(post) == 1
    assert post[0].event.message == "fresh"


@pytest.mark.anyio
async def test_query_time_window_uses_event_timestamp_when_present():
    """A client-supplied timestamp wins over ingested_at for range queries."""
    store = EventStore()

    far_past = datetime.now(timezone.utc) - timedelta(days=3)
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)

    await store.ingest(
        [
            _event(message="old-event", timestamp=far_past),
            _event(message="recent-event", timestamp=recent),
        ],
        batch_id="b-window",
    )

    in_last_hour = await store.query(
        since=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    messages = [se.event.message for se in in_last_hour]
    assert "recent-event" in messages
    assert "old-event" not in messages
