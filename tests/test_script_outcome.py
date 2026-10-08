"""Pattern 10: failures must not report as success (operator scripts).

Covers the shared scripts/script_outcome.py exit-code contract and its
adoption in scripts/adversarial_battery.py: a run whose cleanup left keys
behind, and a run where every check skipped, must not exit 0.
"""

from __future__ import annotations

import os

import pytest

import scripts.script_outcome as outcome
from scripts.script_outcome import EXIT_FAILED, EXIT_INCOMPLETE, EXIT_OK


@pytest.mark.parametrize(
    ("failed", "held", "incomplete", "want"),
    [
        pytest.param(0, 3, 0, EXIT_OK, id="all-held"),
        pytest.param(1, 3, 0, EXIT_FAILED, id="one-failed"),
        pytest.param(2, 0, 1, EXIT_FAILED, id="failed-beats-incomplete"),
        pytest.param(0, 2, 1, EXIT_INCOMPLETE, id="cleanup-left-behind"),
        pytest.param(0, 0, 0, EXIT_INCOMPLETE, id="all-skipped"),
    ],
)
def test_exit_code_contract(failed: int, held: int, incomplete: int, want: int) -> None:
    assert outcome.exit_code(failed=failed, held=held, incomplete=incomplete) == want
    if want == EXIT_OK:
        assert want == 0


def _load_battery(monkeypatch: pytest.MonkeyPatch):
    import importlib
    import sys

    monkeypatch.setattr(sys, "argv", ["adversarial_battery.py"])
    sys.modules.pop("scripts.adversarial_battery", None)
    return importlib.import_module("scripts.adversarial_battery")


@pytest.fixture()
def battery(monkeypatch: pytest.MonkeyPatch):
    module = _load_battery(monkeypatch)
    monkeypatch.setattr(module, "RESULTS", [])
    monkeypatch.setenv("API_URL", "http://localhost:8000")
    monkeypatch.setenv("BOOTSTRAP_KEY", "test-key")
    monkeypatch.setattr(
        module, "resolve_live_target", lambda *args, **kwargs: "http://localhost:8000"
    )
    return module


def _run_main(battery_module, monkeypatch, *, checks, revoke_result):
    """Run battery.main with stubbed provision/checks/cleanup."""
    monkeypatch.setattr(
        battery_module,
        "provision",
        lambda issued: (
            "sponsor-1",
            {"wallet_id": "a"},
            {"wallet_id": "b"},
            {"permit_id": "p"},
            {},
        ),
    )

    def fake_checks(sponsor_id, a, b, permit):
        for name, passed in checks:
            battery_module.record(name, passed, "stubbed")

    monkeypatch.setattr(battery_module, "run_checks", fake_checks)
    monkeypatch.setattr(battery_module, "revoke_all", lambda issued: revoke_result)
    return battery_module.main([])


def test_revoke_all_returns_keys_left_behind(battery, monkeypatch) -> None:
    monkeypatch.setattr(battery, "req", lambda *args, **kwargs: (500, {}))
    issued = [
        {"wallet_id": "w1", "key_id": "k1", "label": "adv-a-key1"},
        {"wallet_id": "w1", "key_id": "k2", "label": "adv-a-key2"},
    ]
    assert battery.revoke_all(issued) == ["adv-a-key1", "adv-a-key2"]


def test_revoke_all_clean_when_all_revoked(battery, monkeypatch) -> None:
    monkeypatch.setattr(battery, "req", lambda *args, **kwargs: (200, {}))
    issued = [{"wallet_id": "w1", "key_id": "k1", "label": "adv-a-key1"}]
    assert battery.revoke_all(issued) == []


def test_main_all_skipped_does_not_exit_zero(battery, monkeypatch) -> None:
    code = _run_main(
        battery, monkeypatch, checks=[("c1", None), ("c2", None)], revoke_result=[]
    )
    assert code == EXIT_INCOMPLETE
    assert code != 0


def test_main_cleanup_failure_does_not_exit_zero(battery, monkeypatch) -> None:
    code = _run_main(
        battery,
        monkeypatch,
        checks=[("wallet_isolation", True)],
        revoke_result=["adv-a-key1"],
    )
    assert code == EXIT_INCOMPLETE
    assert code != 0


def test_main_failed_check_exits_failed(battery, monkeypatch) -> None:
    code = _run_main(
        battery,
        monkeypatch,
        checks=[("wallet_isolation", False)],
        revoke_result=[],
    )
    assert code == EXIT_FAILED


def test_main_all_held_clean_exits_zero(battery, monkeypatch) -> None:
    code = _run_main(
        battery,
        monkeypatch,
        checks=[("wallet_isolation", True), ("invalid_key_rejected", True)],
        revoke_result=[],
    )
    assert code == EXIT_OK
    assert os.environ["API_URL"] == "http://localhost:8000"
