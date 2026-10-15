"""Fail-closed coverage for the standalone auto-PR runner.

The runner calls the telemetry proof surface with an ``X-API-Key``. It must
refuse to send a request without a configured key and fail when the API
rejects the request, while a correctly configured run still succeeds.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "auto_pr_runner.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "auto-pr.yml"
API_URL = "https://middleware.example.test"


def _load_runner():
    spec = importlib.util.spec_from_file_location("auto_pr_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _no_http(*args, **kwargs):
    raise AssertionError("no HTTP request may be sent without a configured API key")


def _set_key(monkeypatch, api_key):
    if api_key is None:
        monkeypatch.delenv("API_KEY", raising=False)
    else:
        monkeypatch.setenv("API_KEY", api_key)


def _recording_get(status, body, seen):
    def fake_get(url, *, params=None, headers=None, timeout=None):
        seen.append(headers)
        return httpx.Response(status, json=body)

    return fake_get


@pytest.mark.proof
def test_no_literal_dev_key_fallback():
    assert "dev-key" not in RUNNER_PATH.read_text()


@pytest.mark.proof
def test_frozen_auto_pr_workflow_is_absent():
    assert not WORKFLOW_PATH.exists()


# --- scripts/auto_pr_runner.py ---------------------------------------------


@pytest.mark.proof
@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_runner_exits_nonzero_without_api_key(monkeypatch, tmp_path, api_key):
    runner = _load_runner()
    monkeypatch.setenv("API_URL", API_URL)
    _set_key(monkeypatch, api_key)
    monkeypatch.setenv("FIX_OUTPUT", str(tmp_path / "fix.json"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(runner.httpx, "get", _no_http)
    monkeypatch.setattr(runner.httpx, "post", _no_http)

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1
    assert not (tmp_path / "fix.json").exists()


@pytest.mark.proof
@pytest.mark.parametrize("status", [401, 403])
def test_runner_fails_when_api_rejects_key(monkeypatch, tmp_path, status):
    runner = _load_runner()
    monkeypatch.setenv("API_URL", API_URL)
    monkeypatch.setenv("API_KEY", "configured-key")
    monkeypatch.setenv("FIX_OUTPUT", str(tmp_path / "fix.json"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    seen: list = []
    monkeypatch.setattr(
        runner.httpx, "get", _recording_get(status, {"detail": "denied"}, seen)
    )
    monkeypatch.setattr(runner.httpx, "post", _no_http)

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 1
    assert seen == [{"X-API-Key": "configured-key"}]
    assert not (tmp_path / "fix.json").exists()


@pytest.mark.proof
def test_runner_with_configured_key_still_succeeds(monkeypatch, tmp_path):
    runner = _load_runner()
    monkeypatch.setenv("API_URL", API_URL)
    monkeypatch.setenv("API_KEY", "configured-key")
    monkeypatch.setenv("FIX_OUTPUT", str(tmp_path / "fix.json"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    seen: list = []
    monkeypatch.setattr(
        runner.httpx, "get", _recording_get(200, {"anomalies": []}, seen)
    )
    monkeypatch.setattr(runner.httpx, "post", _no_http)

    with pytest.raises(SystemExit) as exc:
        runner.main()

    assert exc.value.code == 0
    assert seen == [{"X-API-Key": "configured-key"}]
