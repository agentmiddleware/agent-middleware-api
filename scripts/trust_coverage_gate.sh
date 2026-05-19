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

TRUST_COVERAGE_TESTS=(
  tests/test_golden_path.py
  tests/test_demo_trust_plane.py
  tests/test_agent_ops_war_room_demo.py
  tests/test_me_trust_ledger.py
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

TRUST_COVERAGE_MODULES=(
  app.routers.mcp
  app.routers.permits
  app.routers.receipts
  app.routers.keys
  app.routers.audit
  app.routers.me
  app.services.permits
  app.services.receipts
  app.services.signing_keys
  app.services.idempotency
  app.core.trust_mode
)

COV_ARGS=()
for module in "${TRUST_COVERAGE_MODULES[@]}"; do
  COV_ARGS+=("--cov=$module")
done

echo "[trust-coverage] enforcing 80% coverage over trust-plane control modules"
"${PYTEST_CMD[@]}" -q \
  "${TRUST_COVERAGE_TESTS[@]}" \
  "${COV_ARGS[@]}" \
  --cov-report=term-missing \
  --cov-fail-under=80

echo "[trust-coverage] trust coverage gate passed"
