"""Wiring for the site regression gate.

The browser regression scripts used to run outside every gate: no Makefile
target invoked them, and a failing script stopped its own run at the first
broken assertion with no summary of what else ran. These tests pin the fix:
the Makefile target exists and names the runner, the runner invokes all
three scripts, and a failing script neither stops the rest nor hides in the
report.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
RUNNER = ROOT / "scripts" / "site_regression_gate.sh"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SCRIPTS = (
    "tests/test_arcade_regressions.mjs",
    "tests/test_site_design.mjs",
    "tests/test_site_pilot_fit.mjs",
)

node = shutil.which("node")
bash = shutil.which("bash")

requires_node = pytest.mark.skipif(node is None, reason="node is required")
requires_bash = pytest.mark.skipif(bash is None, reason="bash is required")


def test_makefile_names_the_regression_gate() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "site-regression-gate:" in text
    assert "scripts/site_regression_gate.sh" in text


def test_runner_invokes_all_three_scripts() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    for script in SCRIPTS:
        assert script.removeprefix("tests/") in text, script


def test_ci_runs_the_server_less_arcade_check() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "node --test tests/test_arcade_regressions.mjs" in text


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@requires_node
@requires_bash
def test_runner_runs_every_script_and_reports_each(tmp_path: Path) -> None:
    """A failing script must not stop the rest, and the summary names each."""
    _write_stub(tmp_path / "test_arcade_regressions.mjs", 'console.log("arcade ok");\n')
    _write_stub(
        tmp_path / "test_site_design.mjs",
        'console.log("design broke");\nprocess.exit(1);\n',
    )
    _write_stub(tmp_path / "test_site_pilot_fit.mjs", 'console.log("pilot ok");\n')
    env = {
        **os.environ,
        "SITE_GATE_TESTS_DIR": str(tmp_path),
        "SITE_GATE_NO_SERVE": "1",
    }
    completed = subprocess.run(
        [bash, str(RUNNER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 1
    assert "arcade ok" in completed.stdout
    assert "design broke" in completed.stdout
    assert "pilot ok" in completed.stdout
    assert "2 passed, 1 failed" in completed.stdout
    assert "PASS  arcade regressions (node --test)" in completed.stdout
    assert "FAIL" in completed.stdout and "test_site_design.mjs" in completed.stdout
    assert "PASS" in completed.stdout and "test_site_pilot_fit.mjs" in completed.stdout


@requires_node
@requires_bash
def test_runner_passes_when_every_script_passes(tmp_path: Path) -> None:
    for name in (
        "test_arcade_regressions.mjs",
        "test_site_design.mjs",
        "test_site_pilot_fit.mjs",
    ):
        _write_stub(tmp_path / name, 'console.log("ok");\n')
    env = {
        **os.environ,
        "SITE_GATE_TESTS_DIR": str(tmp_path),
        "SITE_GATE_NO_SERVE": "1",
    }
    completed = subprocess.run(
        [bash, str(RUNNER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "3 passed, 0 failed" in completed.stdout
