"""Fail-closed guards for scripts/auto_pr_runner.py.

The runner used to catch only httpx.ConnectError (so a timeout or TLS/DNS
failure escaped as a traceback) and trusted the anomaly feed's shape and
fields (so a malformed feed caused KeyError/AttributeError crashes, and an
anomaly_id with a slash would land in a URL path segment).
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "auto_pr_runner.py"
API_URL = "https://middleware.example.test"
ANOMALY = {
    "anomaly_id": "anom-1234",
    "summary": "12/12 errors from one source",
    "severity": "critical",
}
FIX = {"files_changed": ["app/x.py"], "tests_passed": True, "status": "ready"}


def _load_runner():
    spec = importlib.util.spec_from_file_location("auto_pr_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("API_URL", API_URL)
    monkeypatch.setenv("API_KEY", "configured-key")
    monkeypatch.setenv("FIX_OUTPUT", str(tmp_path / "fix.json"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)


def _get(status, body):
    def fake_get(url, *, params=None, headers=None, timeout=None):
        return httpx.Response(status, json=body)

    return fake_get


def _post(status, body, seen):
    def fake_post(url, *, json=None, headers=None, timeout=None):
        seen.append(url)
        return httpx.Response(status, json=body)

    return fake_post


def test_runner_fails_on_transport_errors_beyond_connect(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)

    def timeout_get(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(runner.httpx, "get", timeout_get)

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1


def test_runner_rejects_non_dict_anomaly_payload(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.httpx, "get", _get(200, ["not", "a", "dict"]))

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1


def test_runner_rejects_non_list_anomalies(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.httpx, "get", _get(200, {"anomalies": {}}))

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1


def test_runner_rejects_anomaly_missing_id(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner.httpx, "get", _get(200, {"anomalies": [{"summary": "x"}]})
    )

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1


def test_runner_rejects_anomaly_id_with_path_separator(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)
    bad = dict(ANOMALY, anomaly_id="../escape")
    monkeypatch.setattr(runner.httpx, "get", _get(200, {"anomalies": [bad]}))
    seen: list = []
    monkeypatch.setattr(runner.httpx, "post", _post(200, FIX, seen))

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1
    assert seen == []


def test_runner_rejects_non_list_files_changed(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.httpx, "get", _get(200, {"anomalies": [ANOMALY]}))
    seen: list = []
    monkeypatch.setattr(
        runner.httpx, "post", _post(200, {"files_changed": "app/x.py"}, seen)
    )

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 2


def test_runner_happy_path_still_writes_fix(monkeypatch, tmp_path):
    runner = _load_runner()
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(runner.httpx, "get", _get(200, {"anomalies": [ANOMALY]}))
    seen: list = []
    monkeypatch.setattr(runner.httpx, "post", _post(200, FIX, seen))

    # The success path returns normally instead of raising SystemExit.
    assert runner.main() is None
    assert seen == [f"{API_URL}/v1/telemetry/anomalies/anom-1234/auto-pr"]
    assert (tmp_path / "fix.json").exists()
