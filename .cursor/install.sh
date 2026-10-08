#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for agent-middleware-api.
#
# Reproduces the developer setup documented in AGENTS.md ("Cursor Cloud specific
# instructions"): install uv, then prepare a gitignored .venv at the repo root
# holding everything in requirements.txt plus ruff, so every dev tool
# (.venv/bin/{pytest,ruff,mypy,uvicorn,alembic,python}) is directly runnable.
#
# Runtime dependencies live in requirements.txt, NOT pyproject.toml. ruff is not
# pinned there, so it is installed alongside — matching the documented layout.
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Require uv (at ~/.local/bin or on PATH). This script deliberately does
#    NOT fetch and execute a remote installer: piping a URL to sh runs
#    unaudited code with the caller's privileges and cannot be pinned or
#    checksum-verified from here. Install uv yourself first, for example:
#
#      curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
#      sh /tmp/uv-install.sh
#
#    Inspect /tmp/uv-install.sh before running it, then re-run this script.
#    Login shells already include ~/.local/bin; non-login shells often do
#    not, so export it before the presence check.
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "[install] uv is not installed; refusing to fetch a remote installer." >&2
  echo "[install] install uv manually (see the comment at the top of $0), then re-run." >&2
  exit 1
fi

# 2. Create the .venv only if missing (keeps re-runs idempotent), then always
#    refresh runtime + dev deps plus ruff. uv resolves the interpreter,
#    downloading 3.12 if the base image lacks it.
if [ ! -x .venv/bin/python ]; then
  uv venv .venv --python 3.12
fi
uv pip install --python .venv/bin/python -r requirements.txt ruff

echo "[install] .venv ready — pytest/ruff/mypy/uvicorn/alembic available under .venv/bin"
