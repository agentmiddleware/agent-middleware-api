"""The live stress script must leave a cleanup manifest on its target.

Every run writes a JSON manifest naming the target, run id, and created
wallet ids (identifiers only, never keys), and refreshes its outcome when
the run finishes. These cases drive ``main()`` with stubbed wallets and
no-op sub-tests, plus pure unit coverage for the manifest helpers.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts import stress_test_live as stress


def run_main(monkeypatch, tmp_path, **overrides):
    async def fake_setup_wallets():
        return "spn-manifest", "agt-manifest"

    async def no_op(*args, **kwargs):
        return None

    async def failing(*args, **kwargs):
        raise AssertionError("synthetic sub-test failure")

    monkeypatch.setenv("AGENT_MIDDLEWARE_API_KEY", "manifest-test-key")
    monkeypatch.setattr(stress, "SEM", asyncio.Semaphore(10))
    monkeypatch.setattr(stress, "setup_wallets", fake_setup_wallets)
    for name in (
        "test_budget_exhaustion",
        "test_expired_permit",
        "test_concurrent_permit_creation",
        "test_concurrent_governed_invokes",
        "test_unicode_payload",
        "test_tampered_permit",
        "test_cross_wallet_access",
        "test_timezone_extremes",
        "test_decimal_precision",
        "test_rapid_fire_idempotency",
        "test_permit_reuse_after_replay",
        "test_health_under_load",
    ):
        monkeypatch.setattr(
            stress, name, failing if overrides.get(name) == "fail" else no_op
        )
    manifest = tmp_path / "run-manifest.json"
    argv = [
        "--api-url",
        "http://127.0.0.1:8000",
        "--manifest-path",
        str(manifest),
    ]
    return asyncio.run(stress.main(argv)), manifest


def test_passing_run_writes_manifest_with_wallet_ids(monkeypatch, tmp_path):
    code, manifest = run_main(monkeypatch, tmp_path)
    assert code == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["script"] == "scripts/stress_test_live.py"
    assert payload["target"] == "http://127.0.0.1:8000"
    assert payload["sponsor_wallet_id"] == "spn-manifest"
    assert payload["agent_wallet_id"] == "agt-manifest"
    assert payload["outcome"] == "passed"
    assert payload["run_id"]
    assert "api_key" not in json.dumps(payload).lower()


def test_failing_run_records_failure_in_manifest(monkeypatch, tmp_path):
    code, manifest = run_main(monkeypatch, tmp_path, test_unicode_payload="fail")
    assert code == 1
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["outcome"].startswith("failed:")
    assert payload["agent_wallet_id"] == "agt-manifest"


def test_build_run_manifest_carries_no_key_material():
    payload = stress.build_run_manifest(
        target="http://127.0.0.1:8000",
        started_at="2026-10-08T00:00:00+00:00",
        outcome="running",
        sponsor_wallet_id="spn-1",
        agent_wallet_id="agt-1",
    )
    assert payload["sponsor_wallet_id"] == "spn-1"
    assert "cleanup" in payload and payload["cleanup"]
    assert "api_key" not in json.dumps(payload).lower()


def test_write_run_manifest_round_trips(tmp_path: Path):
    path = tmp_path / "nested" / "manifest.json"
    payload = {"run_id": "abc", "outcome": "passed"}
    assert stress.write_run_manifest(str(path), payload) == str(path)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
