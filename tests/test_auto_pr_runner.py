"""Fail-closed coverage for the frozen auto-PR runner and its workflow.

``scripts/auto_pr_runner.py`` and the inline ``anomalies`` step of
``.github/workflows/auto-pr.yml`` call the telemetry proof surface with an
``X-API-Key``. Both used to fall back to the literal ``dev-key`` when the
``API_KEY`` secret was missing, and the workflow exited 0 when the API
rejected the request, so a misconfigured run went green. Both must refuse to
send any request without a configured key and fail the job on an auth (or any
other non-200) response, while a correctly configured run still succeeds.
"""

import importlib.util
import shlex
from pathlib import Path

import httpx
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "auto_pr_runner.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "auto-pr.yml"
API_URL = "https://middleware.example.test"
ANOMALY = {
    "anomaly_id": "anom-1234",
    "summary": "12/12 errors from one source",
    "severity": "critical",
}


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


def _workflow_step_source() -> str:
    """The Python program the ``anomalies`` step hands to ``python -c``."""
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["analyze-and-fix"]["steps"]
    [step] = [s for s in steps if s.get("id") == "anomalies"]
    argv = shlex.split(step["run"])
    assert argv[:2] == ["python", "-c"] and len(argv) == 3, argv[:2]
    return argv[2]


def _run_workflow_step(monkeypatch, tmp_path, api_key, *, get=_no_http, post=_no_http):
    """Execute the workflow step's program; return (exit code, GITHUB_OUTPUT)."""
    source = _workflow_step_source()
    monkeypatch.setenv("API_URL", API_URL)
    _set_key(monkeypatch, api_key)
    github_output = tmp_path / "github_output"
    github_output.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    code = 0
    try:
        exec(compile(source, str(WORKFLOW_PATH), "exec"), {"__name__": "__main__"})
    except SystemExit as exc:
        code = exc.code
    return code, github_output.read_text()


def _recording_get(status, body, seen):
    def fake_get(url, *, params=None, headers=None, timeout=None):
        seen.append(headers)
        return httpx.Response(status, json=body)

    return fake_get


@pytest.mark.proof
def test_no_literal_dev_key_fallback():
    assert "dev-key" not in RUNNER_PATH.read_text()
    assert "dev-key" not in WORKFLOW_PATH.read_text()


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


# --- .github/workflows/auto-pr.yml -----------------------------------------


@pytest.mark.proof
@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_workflow_fails_without_api_key(monkeypatch, tmp_path, api_key):
    code, github_output = _run_workflow_step(monkeypatch, tmp_path, api_key)

    assert code not in (0, None)
    assert "has_fix" not in github_output


@pytest.mark.proof
@pytest.mark.parametrize("status", [401, 403, 500])
def test_workflow_fails_when_anomaly_fetch_is_rejected(monkeypatch, tmp_path, status):
    seen: list = []
    code, github_output = _run_workflow_step(
        monkeypatch,
        tmp_path,
        "configured-key",
        get=_recording_get(status, {"detail": "denied"}, seen),
    )

    assert code not in (0, None)
    assert seen == [{"X-API-Key": "configured-key"}]
    assert "has_fix" not in github_output


@pytest.mark.proof
@pytest.mark.parametrize("status", [401, 403, 500])
def test_workflow_fails_when_fix_generation_is_rejected(monkeypatch, tmp_path, status):
    seen: list = []

    def fake_post(url, *, json=None, headers=None, timeout=None):
        seen.append(headers)
        return httpx.Response(status, json={"detail": "denied"})

    code, github_output = _run_workflow_step(
        monkeypatch,
        tmp_path,
        "configured-key",
        get=_recording_get(200, {"anomalies": [ANOMALY]}, seen),
        post=fake_post,
    )

    assert code not in (0, None)
    assert seen == [{"X-API-Key": "configured-key"}] * 2
    assert "has_fix" not in github_output


@pytest.mark.proof
def test_workflow_with_configured_key_still_succeeds(monkeypatch, tmp_path):
    seen: list = []
    code, github_output = _run_workflow_step(
        monkeypatch,
        tmp_path,
        "configured-key",
        get=_recording_get(200, {"anomalies": []}, seen),
    )

    assert code in (0, None)
    assert seen == [{"X-API-Key": "configured-key"}]
    assert "has_fix" not in github_output
