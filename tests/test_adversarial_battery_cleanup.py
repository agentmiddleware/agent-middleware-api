"""Failed test-key cleanup must fail the adversarial battery.

``scripts/adversarial_battery.py`` used to print a FAILED cleanup line and
still exit 0 when every probe passed, leaving live test keys behind with a
passing exit code. ``revoke_all`` now returns the failure count and ``main``
records it as a check, so a failed revoke flips the run to FAIL / exit 1.
"""

import pytest

from scripts import adversarial_battery as battery


@pytest.fixture(autouse=True)
def _clean_results():
    battery.RESULTS.clear()
    yield
    battery.RESULTS.clear()


def _issued():
    return [
        {"wallet_id": "w1", "key_id": "k1", "label": "agent-a-key-1"},
        {"wallet_id": "w1", "key_id": "k2", "label": "agent-a-key-2"},
    ]


def test_revoke_all_returns_zero_when_every_key_revoked(monkeypatch):
    monkeypatch.setattr(battery, "req", lambda *args, **kwargs: (200, {}))

    assert battery.revoke_all(_issued()) == 0


def test_revoke_all_counts_keys_that_failed_to_revoke(monkeypatch, capsys):
    calls = []

    def fake_req(*args, **kwargs):
        calls.append(args)
        return (500, {}) if len(calls) == 1 else (200, {})

    monkeypatch.setattr(battery, "req", fake_req)

    assert battery.revoke_all(_issued()) == 1
    out = capsys.readouterr()
    assert "FAILED(status=500)" in out.out
    assert "CLEANUP FAILED" in out.err


def test_revoke_all_treats_already_gone_as_success(monkeypatch):
    monkeypatch.setattr(battery, "req", lambda *args, **kwargs: (404, {}))

    assert battery.revoke_all(_issued()) == 0


def _stub_run(monkeypatch, cleanup_failures):
    monkeypatch.setenv("API_URL", "https://staging.example.test")
    monkeypatch.setenv("BOOTSTRAP_KEY", "test-bootstrap-key")
    monkeypatch.setattr(battery, "resolve_live_target", lambda target, **kwargs: target)
    monkeypatch.setattr(battery, "provision", lambda issued: ("s", {}, {}, {}, {}))
    monkeypatch.setattr(
        battery, "run_checks", lambda *args: battery.record("dummy", True, "ok")
    )
    monkeypatch.setattr(battery, "revoke_all", lambda issued: cleanup_failures)


def test_main_fails_when_cleanup_fails_even_if_checks_pass(monkeypatch):
    _stub_run(monkeypatch, cleanup_failures=1)

    assert battery.main([]) == 1
    verdicts = {name: verdict for name, verdict, _ in battery.RESULTS}
    assert verdicts["test_key_cleanup"] == "FAIL"


def test_main_passes_when_checks_and_cleanup_pass(monkeypatch):
    _stub_run(monkeypatch, cleanup_failures=0)

    assert battery.main([]) == 0
    verdicts = {name: verdict for name, verdict, _ in battery.RESULTS}
    assert verdicts["test_key_cleanup"] == "PASS"
