#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python3.12}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

CORE_PATHS=(
  app/trust
  app/core
  app/db
  app/routers/mcp.py
  app/routers/permits.py
  app/routers/receipts.py
  app/routers/audit.py
  app/routers/evidence.py
  app/routers/keys.py
  app/routers/me.py
  app/routers/billing.py
  app/routers/api_keys.py
  app/routers/kyc.py
  app/routers/trust_readiness.py
)

echo "[core-quality] ruff trust/core slice"
"$PYTHON_BIN" -m ruff check \
  "${CORE_PATHS[@]}" \
  --select E,F,I,UP,B,ASYNC \
  --ignore E501 \
  --config 'lint.flake8-bugbear.extend-immutable-calls = ["fastapi.Depends", "fastapi.Query", "fastapi.Header", "fastapi.Body", "fastapi.Form", "fastapi.File", "fastapi.Path"]'

echo "[core-quality] mypy trust/core slice"
"$PYTHON_BIN" -m mypy \
  "${CORE_PATHS[@]}" \
  --follow-imports=skip \
  --warn-redundant-casts \
  --check-untyped-defs \
  --no-warn-return-any

echo "[core-quality] passed"
