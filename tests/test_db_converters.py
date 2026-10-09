"""Corrupt stored JSON must be logged and counted, not read as empty in silence."""

import logging
from datetime import datetime
from decimal import Decimal

import pytest

import app.db.converters as converters
from app.db.converters import (
    content_piece_model_to_schema,
    indexed_api_model_to_schema,
    ledger_entry_model_to_schema,
    parse_metadata_json,
    scan_model_to_report,
    telemetry_event_model_to_schema,
    vulnerability_model_to_schema,
    wallet_model_to_response,
)
from app.db.models import (
    ContentPieceModel,
    LedgerEntryModel,
    OracleIndexedAPIModel,
    SecurityScanModel,
    SecurityVulnerabilityModel,
    TelemetryEventModel,
    WalletModel,
)

# A marker planted in the broken text. The alarm must not copy stored JSON
# into the log, because metadata and evidence can hold customer data.
SECRET_MARKER = "do-not-log-this-stored-value"

WHEN = datetime(2026, 10, 8, 12, 0, 0)


def _counts() -> dict[str, int]:
    reader = getattr(converters, "corrupt_stored_json_counts", None)
    if reader is None:
        return {}
    return reader()


@pytest.fixture(autouse=True)
def _isolated_corrupt_counts():
    reset = getattr(converters, "reset_corrupt_stored_json_counts", None)
    if reset is not None:
        reset()
    yield
    if reset is not None:
        reset()


def _alarms(caplog: pytest.LogCaptureFixture, field: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and "corrupt_stored_json" in record.getMessage()
        and f"field={field}" in record.getMessage()
    ]


def _wallet(**overrides) -> WalletModel:
    values = {
        "wallet_id": "wal_1",
        "wallet_type": "sponsor",
        "balance": Decimal("1.50"),
        "lifetime_credits": Decimal("2"),
        "lifetime_debits": Decimal("0.50"),
        "created_at": WHEN,
    }
    values.update(overrides)
    return WalletModel(**values)


def _ledger(**overrides) -> LedgerEntryModel:
    values = {
        "entry_id": "ent_1",
        "wallet_id": "wal_1",
        "action": "credit",
        "amount": Decimal("1"),
        "balance_after": Decimal("1"),
        "timestamp": WHEN,
    }
    values.update(overrides)
    return LedgerEntryModel(**values)


def _indexed_api(**overrides) -> OracleIndexedAPIModel:
    values = {
        "api_id": "api_1",
        "url": "https://example.test/agent",
        "name": "Example",
        "description": "A directory entry",
        "directory_type": "well_known",
        "compatibility_tier": "native",
        "compatibility_score": 0.5,
        "capabilities_json": '[{"name": "search", "description": "find"}]',
        "tags_json": '["ai"]',
        "status": "indexed",
        "last_crawled": WHEN,
    }
    values.update(overrides)
    return OracleIndexedAPIModel(**values)


def test_valid_stored_json_is_unchanged_and_not_counted(caplog):
    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        wallet = wallet_model_to_response(_wallet(metadata_json='{"plan": "pilot"}'))
        ledger = ledger_entry_model_to_schema(
            _ledger(metadata_json='{"source": "stripe"}')
        )
        parsed = parse_metadata_json('{"ok": true}')
        api = indexed_api_model_to_schema(_indexed_api())

    assert wallet.metadata == {"plan": "pilot"}
    assert ledger.metadata == {"source": "stripe"}
    assert parsed == {"ok": True}
    assert [cap.name for cap in api.capabilities] == ["search"]
    assert api.tags == ["ai"]
    assert parse_metadata_json(None) == {}
    assert parse_metadata_json("") == {}
    assert _counts() == {}
    assert caplog.records == []


def test_broken_wallet_and_ledger_metadata_is_logged_and_counted(caplog):
    wallet_raw = '{"plan": ' + SECRET_MARKER
    ledger_raw = "[not-json " + SECRET_MARKER

    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        wallet = wallet_model_to_response(
            _wallet(wallet_id="wal_broken", metadata_json=wallet_raw)
        )
        ledger = ledger_entry_model_to_schema(
            _ledger(entry_id="ent_broken", metadata_json=ledger_raw)
        )
        again = wallet_model_to_response(
            _wallet(wallet_id="wal_broken_2", metadata_json=wallet_raw)
        )

    assert wallet.metadata == {}
    assert ledger.metadata == {}
    assert again.metadata == {}
    wallet_alarms = _alarms(caplog, "wallet.metadata_json")
    ledger_alarms = _alarms(caplog, "ledger.metadata_json")
    assert wallet_alarms, "broken wallet metadata was read as empty with no alarm"
    assert ledger_alarms, "broken ledger metadata was read as empty with no alarm"
    assert "record_id=wal_broken" in wallet_alarms[0]
    assert "reason=json_decode_error" in wallet_alarms[0]
    assert "count=2" in wallet_alarms[1]
    assert "record_id=ent_broken" in ledger_alarms[0]
    assert _counts()["wallet.metadata_json"] == 2
    assert _counts()["ledger.metadata_json"] == 1
    assert SECRET_MARKER not in caplog.text


def test_parse_metadata_json_counts_each_broken_value(caplog):
    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        first = parse_metadata_json(
            "{", field="telemetry.payload_json", record_id="evt_1"
        )
        second = parse_metadata_json(
            "{", field="telemetry.payload_json", record_id="evt_2"
        )
        untouched = parse_metadata_json(None, field="telemetry.payload_json")

    assert first == {}
    assert second == {}
    assert untouched == {}
    alarms = _alarms(caplog, "telemetry.payload_json")
    assert len(alarms) == 2, "broken metadata JSON was read as empty with no alarm"
    assert _counts() == {"telemetry.payload_json": 2}


def test_telemetry_and_content_name_their_corrupt_fields(caplog):
    event = TelemetryEventModel(
        event_id="evt_9",
        batch_id="batch_1",
        event_type="error",
        severity="low",
        source="gateway",
        message="disk full",
        payload_json="{" + SECRET_MARKER,
    )
    piece = ContentPieceModel(
        content_id="piece_9",
        pipeline_id="pipe_1",
        format="text_post",
        title="Launch note",
        download_url="https://example.test/piece",
        status="ready",
        metadata_json="{" + SECRET_MARKER,
        generated_at=WHEN,
    )

    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        read_event = telemetry_event_model_to_schema(event)
        read_piece = content_piece_model_to_schema(piece)

    assert read_event.metadata == {}
    assert read_piece.metadata == {}
    assert _alarms(caplog, "telemetry.payload_json"), (
        "broken telemetry payload was read as empty with no alarm"
    )
    assert _alarms(caplog, "content.metadata_json"), (
        "broken content metadata was read as empty with no alarm"
    )
    assert "record_id=evt_9" in _alarms(caplog, "telemetry.payload_json")[0]
    assert "record_id=piece_9" in _alarms(caplog, "content.metadata_json")[0]
    assert _counts()["telemetry.payload_json"] == 1
    assert _counts()["content.metadata_json"] == 1
    assert SECRET_MARKER not in caplog.text


def test_broken_oracle_json_is_logged_and_counted(caplog):
    row = _indexed_api(
        capabilities_json="{not-json " + SECRET_MARKER,
        tags_json="[not-a-list " + SECRET_MARKER,
    )

    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        api = indexed_api_model_to_schema(row)

    assert api.capabilities == []
    assert api.tags == []
    assert _alarms(caplog, "oracle.capabilities_json"), (
        "broken capability JSON was read as an empty list with no alarm"
    )
    assert _alarms(caplog, "oracle.tags_json"), (
        "broken tag JSON was read as an empty list with no alarm"
    )
    assert "record_id=api_1" in _alarms(caplog, "oracle.capabilities_json")[0]
    assert _counts()["oracle.capabilities_json"] == 1
    assert _counts()["oracle.tags_json"] == 1
    assert SECRET_MARKER not in caplog.text


def test_oracle_wrong_shape_is_counted_and_valid_capabilities_stay(caplog):
    row = _indexed_api(
        capabilities_json=(
            '[{"name": "search", "description": "find"}, "not-a-capability"]'
        ),
        tags_json='{"not": "a list"}',
    )

    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        api = indexed_api_model_to_schema(row)

    # A later bad item must not wipe capabilities that already parsed.
    assert [cap.name for cap in api.capabilities] == ["search"]
    assert api.tags == []
    cap_alarms = _alarms(caplog, "oracle.capabilities_json")
    tag_alarms = _alarms(caplog, "oracle.tags_json")
    assert cap_alarms, "invalid capabilities were dropped with no alarm"
    assert tag_alarms, "non-list tags were read as an empty list with no alarm"
    assert "reason=validation_error" in cap_alarms[0]
    assert "reason=not_a_list" in tag_alarms[0]
    assert _counts()["oracle.capabilities_json"] == 1
    assert _counts()["oracle.tags_json"] == 1


def test_scan_lists_and_evidence_count_broken_json(caplog):
    scan = SecurityScanModel(
        scan_id="scan_1",
        scan_type="internal",
        status="completed",
        targets_json="{not-json",
        attack_categories_json='{"not": "a list"}',
        recommendations_json='["patch the gate"]',
        security_score=80,
        total_tests_run=3,
        total_passed=2,
        total_failed=1,
        started_at=WHEN,
        completed_at=WHEN,
    )
    vuln = SecurityVulnerabilityModel(
        vuln_id="vuln_1",
        scan_id="scan_1",
        category="injection",
        severity="low",
        title="Header reflected",
        endpoint="/v1/example",
        evidence_json="{not-json " + SECRET_MARKER,
        discovered_at=WHEN,
    )
    kept = SecurityVulnerabilityModel(
        vuln_id="vuln_2",
        scan_id="scan_1",
        category="injection",
        severity="info",
        title="Note",
        endpoint="/v1/example",
        evidence_json="[1, 2]",
        discovered_at=WHEN,
    )

    with caplog.at_level(logging.WARNING, logger="app.db.converters"):
        report = scan_model_to_report(scan, [vuln])
        wrapped = vulnerability_model_to_schema(kept)

    assert report.target_services == []
    assert report.attack_categories == []
    assert report.recommendations == ["patch the gate"]
    assert report.vulnerabilities[0].evidence == {}
    # A JSON value that is not an object is wrapped, not treated as corrupt.
    assert wrapped.evidence == {"value": [1, 2]}
    assert _alarms(caplog, "scan.targets_json"), (
        "broken scan targets were read as an empty list with no alarm"
    )
    assert _alarms(caplog, "scan.attack_categories_json"), (
        "non-list attack categories were read as an empty list with no alarm"
    )
    assert _alarms(caplog, "vulnerability.evidence_json"), (
        "broken evidence JSON was read as an empty object with no alarm"
    )
    assert "reason=not_a_list" in _alarms(caplog, "scan.attack_categories_json")[0]
    assert "record_id=scan_1" in _alarms(caplog, "scan.targets_json")[0]
    assert "record_id=vuln_1" in _alarms(caplog, "vulnerability.evidence_json")[0]
    assert _counts()["scan.targets_json"] == 1
    assert _counts()["scan.attack_categories_json"] == 1
    assert _counts().get("scan.recommendations_json") is None
    assert _counts()["vulnerability.evidence_json"] == 1
    assert SECRET_MARKER not in caplog.text
