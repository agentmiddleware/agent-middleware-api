# shellcheck shell=bash
#
# Shared interpreter resolution for the trust gate scripts.
#
# Sourcing this file sets two arrays:
#   PYTHON_CMD  — runs a Python script (e.g. "${PYTHON_CMD[@]}" scripts/foo.py)
#   PYTEST_CMD  — runs pytest       (e.g. "${PYTEST_CMD[@]}" -q tests/)
#
# Selection order:
#   1. Explicit PYTHON / PYTEST environment overrides, used verbatim.
#   2. The first of python3.12, python3, python that can actually import pytest.
#      Probing for pytest (rather than mere existence) is the point: a machine
#      can have a bare system python3.12 on PATH while the project's deps live
#      somewhere else entirely, and picking it produced "No module named pytest".
#      In CI, setup-python puts the dep-installed interpreter first, so this
#      resolves exactly as it always did.
#   3. uv, matching how every other Makefile target runs this project
#      (`uv run --with-requirements requirements.txt`), so a fresh checkout with
#      no local install still runs the gates.

_python_env_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$script_dir/../.." && pwd
}

REPO_ROOT="$(_python_env_repo_root)"

# The gates reference tests/ and scripts/ relatively, and uv needs to find
# requirements.txt, so anchor everything at the repo root.
cd "$REPO_ROOT"

_python_env_has_pytest() {
  "$1" -m pytest --version >/dev/null 2>&1
}

PYTHON_CMD=()
PYTEST_CMD=()

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_CMD=("$PYTHON")
else
  for _candidate in python3.12 python3 python; do
    if command -v "$_candidate" >/dev/null 2>&1 && _python_env_has_pytest "$_candidate"; then
      PYTHON_CMD=("$_candidate")
      break
    fi
  done
fi

if [[ ${#PYTHON_CMD[@]} -eq 0 ]]; then
  if command -v uv >/dev/null 2>&1; then
    PYTHON_CMD=(uv run --with-requirements requirements.txt python)
  else
    echo "[python-env] No interpreter with pytest installed, and uv is not available." >&2
    echo "[python-env] Fix with one of:" >&2
    echo "[python-env]   - install uv (https://docs.astral.sh/uv/) and re-run" >&2
    echo "[python-env]   - python3 -m pip install -r requirements.txt" >&2
    echo "[python-env]   - PYTHON=/path/to/python scripts/$(basename "$0")" >&2
    exit 1
  fi
fi

if [[ -n "${PYTEST:-}" ]]; then
  PYTEST_CMD=("$PYTEST")
else
  PYTEST_CMD=("${PYTHON_CMD[@]}" -m pytest)
fi

echo "[python-env] python: ${PYTHON_CMD[*]}"
