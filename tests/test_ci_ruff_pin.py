"""CI must install the pre-commit ruff pin and check formatting.

`.pre-commit-config.yaml` pins ruff v0.9.0 and runs the ruff-format hook.
The lint job used to `pip install ruff` (latest) and never ran
`ruff format --check`, so CI could disagree with the hook.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"


def _precommit_ruff_version() -> str:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    match = re.search(
        r"repo: https://github.com/astral-sh/ruff-pre-commit\n\s+rev: v(\d+\.\d+\.\d+)",
        text,
    )
    assert match is not None, "pre-commit ruff rev pin is missing"
    return match.group(1)


def _workflow():
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def _pip_install_lines(script: str) -> list[str]:
    return [
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith("pip install")
    ]


def test_precommit_ruff_pin_is_v0_9_0():
    assert _precommit_ruff_version() == "0.9.0"


def test_ci_ruff_installs_use_precommit_pin():
    version = _precommit_ruff_version()
    workflow = _workflow()
    expected = {
        ("python_sdk", "Build SDK wheel and source distribution"): (
            f"pip install uv pytest pytest-asyncio ruff=={version} mypy"
        ),
        ("lint", "Install dependencies and linters"): (
            f"pip install ruff=={version} mypy"
        ),
    }
    for (job_name, step_name), install in expected.items():
        steps = workflow["jobs"][job_name]["steps"]
        step = next(s for s in steps if s.get("name") == step_name)
        installs = [line for line in _pip_install_lines(step["run"]) if "ruff" in line]
        assert installs == [install]


def test_lint_job_runs_ruff_format_check():
    steps = _workflow()["jobs"]["lint"]["steps"]
    format_steps = [
        s for s in steps if s.get("run", "").strip() == "ruff format --check ."
    ]
    assert [s.get("name") for s in format_steps] == ["Run ruff format check"]
