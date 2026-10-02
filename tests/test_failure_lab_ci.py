"""A negative CI control must measure the defect rather than accept a crash."""

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_broken_control(tmp_path, *, exit_code=0, document=None):
    workflow = (ROOT / ".github/workflows/failure-lab.yml").read_text()
    step = workflow.split("- name: Judge the broken integration (must fail)", 1)[1]
    script = textwrap.dedent(step.split("run: |\n", 1)[1])
    binary = tmp_path / "python"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "if sys.argv[1:3] == ['-m', 'failure_lab.integration_check.judge']:\n"
        "    if '--json' in sys.argv and os.environ['QA_DOCUMENT'] != 'null':\n"
        "        pathlib.Path(sys.argv[sys.argv.index('--json') + 1]).write_text(os.environ['QA_DOCUMENT'])\n"
        "    raise SystemExit(int(os.environ['QA_JUDGE_EXIT']))\n"
        "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n"
    )
    binary.chmod(0o700)
    return subprocess.run(
        ["bash", "-e", "-c", script],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "RUNNER_TEMP": str(tmp_path),
            "QA_JUDGE_EXIT": str(exit_code),
            "QA_DOCUMENT": json.dumps(document),
        },
        capture_output=True,
        text=True,
    )


def _observed_duplicate():
    return {
        "schema": "failure_lab.integration_check/result/1",
        "passed": False,
        "assertions": [
            {
                "assertion": "retry_after_lost_response",
                "passed": False,
                "evidence": {
                    "fault_applied": 1,
                    "governed_calls_for_operation": 2,
                    "downstream_executions": 2,
                    "candidate_error": None,
                },
            }
        ],
    }


@pytest.mark.parametrize("exit_code", [1, 2, 127, 137])
def test_negative_control_process_failure_fails_ci(tmp_path, exit_code):
    assert _run_broken_control(tmp_path, exit_code=exit_code).returncode != 0


def test_negative_control_observed_duplicate_passes(tmp_path):
    result = _run_broken_control(tmp_path, document=_observed_duplicate())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["missing", "empty", "passed", "no_effect", "error"])
def test_negative_control_needs_completed_duplicate_observation(tmp_path, kind):
    document = _observed_duplicate()
    if kind == "missing":
        document = None
    elif kind == "empty":
        document = {}
    elif kind == "passed":
        document["passed"] = True
    elif kind == "no_effect":
        document["assertions"][0]["evidence"]["downstream_executions"] = 0
    else:
        document["assertions"][0]["evidence"]["candidate_error"] = "setup failed"
    assert _run_broken_control(tmp_path, document=document).returncode != 0
