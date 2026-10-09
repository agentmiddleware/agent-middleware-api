"""A cached sweep must never hide persistent test or lint failures."""

import sys

import pytest

from scripts import repo_guardian as guardian


@pytest.mark.parametrize("failure", ["pytest", "ruff", None])
@pytest.mark.parametrize("previous_green", [False, True])
def test_sweep_cache_requires_both_checks(
    monkeypatch, tmp_path, failure, previous_green
):
    for name, filename in [
        ("STATE_DIR", ""),
        ("READINESS_SNAP", "readiness.json"),
        ("SWEEP_FINGERPRINT", "fingerprint.txt"),
    ]:
        monkeypatch.setattr(guardian, name, tmp_path / filename)
    monkeypatch.setattr(sys, "argv", ["repo_guardian.py", "--full"])
    monkeypatch.setattr(guardian, "git", lambda *args: "synthetic-branch")
    monkeypatch.setattr(guardian, "code_fingerprint", lambda: "same-tree")
    monkeypatch.setattr(guardian.shutil, "which", lambda _: None)
    monkeypatch.setattr(guardian, "record_findings", lambda *args: None)
    monkeypatch.setattr(
        guardian,
        "readiness_snapshot",
        lambda: {"verdict": "ready", "total": 0, "items": {}, "critical_gaps": []},
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return failure not in command, 0.0, "synthetic result"

    monkeypatch.setattr(guardian, "run", run)
    if previous_green:
        guardian.SWEEP_FINGERPRINT.write_text("same-tree")
    expected = 1 if failure else 0
    assert guardian.main() == expected
    monkeypatch.setattr(sys, "argv", ["repo_guardian.py"])
    assert guardian.main() == expected
    sweeps = [command for command in commands if "pytest" in command]
    assert len(sweeps) == (2 if failure else 1)
    assert guardian.SWEEP_FINGERPRINT.exists() is (failure is None)
