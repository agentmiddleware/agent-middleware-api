#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python3.12}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
if [[ -n "${PYTEST:-}" ]]; then
  PYTEST_CMD=("$PYTEST")
else
  PYTEST_CMD=("$PYTHON_BIN" -m pytest)
fi
TRUST_TESTS=(
  tests/test_golden_path.py
  tests/test_demo_trust_plane.py
  tests/test_regengine_bridge.py
  tests/test_regengine_bridge_demo.py
  tests/test_mcp_trust.py
  tests/test_mcp_trust_mode.py
  tests/test_trust_operator_inspection.py
  tests/test_signing_key_lifecycle.py
  tests/test_trust_mode_guardrails.py
  tests/test_permits.py
  tests/test_receipts.py
  tests/test_audit_chain.py
  tests/test_idempotency.py
)

echo "[trust-gate] focused trust-plane pytest suite"
"${PYTEST_CMD[@]}" -q "${TRUST_TESTS[@]}"

echo "[trust-gate] trust-core coverage gate"
scripts/trust_coverage_gate.sh

echo "[trust-gate] trust-plane demo proof"
"$PYTHON_BIN" scripts/demo_trust_plane.py --assert

echo "[trust-gate] RegEngine governed bridge proof"
"$PYTHON_BIN" scripts/demo_regengine_bridge.py --assert

echo "[trust-gate] discovery drift checks"
"${PYTEST_CMD[@]}" -q tests/test_discovery_drift.py

echo "[trust-gate] OpenAPI parity"
"$PYTHON_BIN" scripts/export_openapi.py --check

echo "[trust-gate] simulation inventory parity"
"$PYTHON_BIN" scripts/generate_sim_inventory.py --check

echo "[trust-gate] trust release gate passed"
