#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python3.12}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

echo "[trust-gate] full pytest suite"
"$PYTHON_BIN" -m pytest -q

echo "[trust-gate] trust-plane demo proof"
"$PYTHON_BIN" scripts/demo_trust_plane.py --assert

echo "[trust-gate] golden path and drift checks"
"$PYTHON_BIN" -m pytest -q \
  tests/test_golden_path.py \
  tests/test_discovery_drift.py \
  tests/test_demo_trust_plane.py \
  tests/test_trust_operator_inspection.py \
  tests/test_mcp_trust_mode.py \
  tests/test_signing_key_lifecycle.py \
  tests/test_trust_mode_guardrails.py

echo "[trust-gate] OpenAPI parity"
"$PYTHON_BIN" scripts/export_openapi.py --check

echo "[trust-gate] simulation inventory parity"
"$PYTHON_BIN" scripts/generate_sim_inventory.py --check

echo "[trust-gate] trust release gate passed"
