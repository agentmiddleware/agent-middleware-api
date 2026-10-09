"""`make test` must select the proof-marked tenant-isolation tests.

The fast loop filters with `-m "not proof"` while CI runs `-m "not
production_trust"`, so every `@pytest.mark.proof` test in
tests/test_tenant_isolation_hardening.py used to pass locally by never
running and fail only in CI. The `test` Makefile target now re-runs that
file scoped to its proof tests. This gate parses the target's recipe and
checks, through real `pytest --collect-only` selection, that each
proof-marked test in the file is selected by at least one recipe line.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = "tests/test_tenant_isolation_hardening.py"
COLLECT_TIMEOUT_SECONDS = 600


def _test_target_recipe_lines() -> list[str]:
    """Return the raw recipe lines of the `test:` target in the Makefile."""
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    recipe: list[str] = []
    in_target = False
    for line in lines:
        if in_target:
            if line.startswith("\t") or line.startswith("    "):
                recipe.append(line.strip())
                continue
            if line.strip() == "" or line.strip().startswith("#"):
                continue
            break
        if line == "test:":
            in_target = True
    assert recipe, "Makefile has no recipe lines under the `test:` target"
    return recipe


def _marker_expression(recipe_line: str) -> str:
    """Extract the `-m` marker expression from a pytest recipe line."""
    match = re.search(r'-m\s+"([^"]+)"', recipe_line)
    if match is None:
        match = re.search(r"-m\s+'([^']+)'", recipe_line)
    return match.group(1) if match else ""


def _covers_target_file(recipe_line: str) -> bool:
    """Whether a recipe line's pytest paths include the tenant-isolation file."""
    if "pytest" not in recipe_line:
        return False
    if TARGET_FILE in recipe_line:
        return True
    return re.search(r"(?:^|\s)tests(?:/|\s|$)", recipe_line) is not None


def _collect_with_expression(expression: str) -> set[str]:
    """Node IDs selected in the tenant-isolation file under one `-m` filter.

    Runs real pytest collection (no tests execute) so marker semantics stay
    identical to the suite itself. The `uv run` prefix in the Makefile only
    provisions the environment; selection depends on the paths and `-m`.
    """
    command = [
        sys.executable,
        "-m",
        "pytest",
        TARGET_FILE,
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    if expression:
        command += ["-m", expression]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=COLLECT_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"collect-only failed for -m {expression!r}:\n{result.stdout}\n{result.stderr}"
    )
    return {line.strip() for line in result.stdout.splitlines() if "::" in line.strip()}


def test_make_test_selects_proof_marked_tenant_isolation_tests():
    recipe_lines = _test_target_recipe_lines()
    scoped = [line for line in recipe_lines if _covers_target_file(line)]
    assert scoped, (
        "Makefile `test:` target runs no pytest line covering "
        f"{TARGET_FILE}; the proof-marked tenant-isolation tests it "
        "contains are skipped locally while CI runs them."
    )
    selected: set[str] = set()
    for line in scoped:
        selected |= _collect_with_expression(_marker_expression(line))
    expected = _collect_with_expression("proof")
    assert expected, f"no proof-marked tests collected in {TARGET_FILE}"
    missing = sorted(expected - selected)
    assert not missing, (
        f"Makefile `test:` target skips {len(missing)} proof-marked "
        f"tenant-isolation tests that CI runs: {missing}. "
        "The target must select them (for example by re-running "
        f'{TARGET_FILE} scoped to `-m "proof"`).'
    )
