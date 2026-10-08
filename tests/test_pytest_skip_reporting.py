"""Pins skip visibility in the default pytest run.

Skipped security and infra tests kept CI green without proving the behavior,
because a bare ``N skipped`` line hides which tests skipped and why. The
``-rs`` flag in ``pyproject.toml`` makes every run print each skip with its
reason, so new quiet skips stand out in review. This contract fails if the
flag is ever dropped.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _addopts() -> list[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    return list(config["tool"]["pytest"]["ini_options"].get("addopts", []))


def test_default_run_reports_skip_reasons() -> None:
    addopts = _addopts()
    assert any(
        option.startswith("-r") and "s" in option.lstrip("-") for option in addopts
    ), (
        "pyproject addopts must keep a skip-reporting -r flag with 's' "
        f"(got {addopts}); without it skipped tests stay invisible"
    )


def test_skip_summary_names_a_reason() -> None:
    """A skipped test shows its reason under the repo's default flags.

    Runs a one-test probe file inside ``tests/`` with no extra CLI flags, so
    pytest picks up this repo's ``pyproject.toml`` and its ``addopts`` the
    same way every normal run does. Without ``-rs`` the reason below would
    not appear in the output. The probe file is removed afterwards so it
    never enters the suite.
    """
    probe = REPO_ROOT / "tests" / "test_skip_probe_tmp.py"
    probe.write_text(
        "import pytest\n"
        "\n"
        "def test_always_skipped_probe():\n"
        "    pytest.skip('probe reason stays visible')\n"
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "tests/test_skip_probe_tmp.py",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=180,
            check=False,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    assert "probe reason stays visible" in result.stdout, (
        "skip reason missing from default run output; "
        "the -rs flag in pyproject addopts may have been dropped:\n" + result.stdout
    )
