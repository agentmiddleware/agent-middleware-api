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

# 1. Install uv (to ~/.local/bin, already on PATH) if it is not present.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# 2. Create the .venv only if missing (keeps re-runs idempotent), then always
#    refresh runtime + dev deps plus ruff. uv resolves the interpreter,
#    downloading 3.12 if the base image lacks it.
if [ ! -x .venv/bin/python ]; then
  uv venv .venv --python 3.12
fi
uv pip install --python .venv/bin/python -r requirements.txt ruff

echo "[install] .venv ready — pytest/ruff/mypy/uvicorn/alembic available under .venv/bin"
