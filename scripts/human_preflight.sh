#!/usr/bin/env bash
# Human preflight: verify discovery URLs and /health/dependencies (simulation_modes).
# Usage: API_URL=http://localhost:8000 bash scripts/human_preflight.sh
# Requires: curl, python3. Optional: jq for pretty JSON.

set -u

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_URL="${API_URL%/}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

http_code() {
  local path="$1"
  curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 10 \
    "${API_URL}${path}" 2>/dev/null || echo "000"
}

echo "Human preflight — API_URL=${API_URL}"
echo ""

fail=0
check_http() {
  local name="$1"
  local path="$2"
  local want="${3:-200}"
  local code
  code="$(http_code "$path")"
  if [[ "$code" == "$want" ]]; then
    echo -e "${GREEN}OK${NC}  ${code}  ${name}  ${path}"
  else
    echo -e "${RED}BAD${NC} ${code} (expected ${want})  ${name}  ${path}"
    fail=1
  fi
}

check_http "Liveness" "/health" "200"
check_http "OpenAPI" "/openapi.json" "200"
check_http "Agent manifest" "/.well-known/agent.json" "200"
check_http "Discover index" "/v1/discover" "200"
check_http "LLM docs" "/llm.txt" "200"
check_http "MCP tools manifest" "/mcp/tools.json" "200"
check_http "Well-known MCP (alternate route)" "/.well-known/mcp/tools.json" "200"

echo ""
deps_json="$(curl -sS --connect-timeout 3 --max-time 15 "${API_URL}/health/dependencies" 2>/dev/null || true)"
if [[ -z "$deps_json" ]]; then
  echo -e "${RED}FAILED${NC} to fetch /health/dependencies"
  exit 1
fi

echo "Dependency report summary:"
if command -v jq >/dev/null 2>&1; then
  echo "$deps_json" | jq '{status, version, unhealthy, simulation_modes}'
else
  echo "$deps_json"
  echo ""
  echo -e "${YELLOW}Tip:${NC} install jq to print a compact summary (simulation_modes, unhealthy)."
fi

overall="$(echo "$deps_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status",""))' 2>/dev/null || true)"
if [[ "$overall" == "degraded" ]]; then
  echo ""
  echo -e "${YELLOW}Warning:${NC} status is degraded — inspect unhealthy dependencies in the JSON above."
fi

if [[ "$fail" -eq 0 ]]; then
  echo ""
  echo "agent_first alignment:"
  export API_URL
  if python3 -c "
import json
import os
import sys
import urllib.request

base = os.environ['API_URL'].rstrip('/')

def load(path: str) -> dict:
    req = urllib.request.Request(
        f'{base}{path}', headers={'User-Agent': 'human_preflight'}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)

try:
    a = load('/.well-known/agent.json')
    d = load('/v1/discover')
except Exception as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(1) from exc
if a.get('agent_first') != d.get('agent_first'):
    print('agent_first mismatch between manifest and /v1/discover', file=sys.stderr)
    raise SystemExit(1)
"; then
    echo -e "${GREEN}OK${NC}   /.well-known/agent.json and /v1/discover agree on agent_first"
  else
    echo -e "${RED}BAD${NC}   agent_first alignment (see stderr above)"
    fail=1
  fi
fi

echo ""
echo "Next steps for humans:"
echo "  - Read docs/human-onboarding.md"
echo "  - If simulation_modes show true, those domains are simulated unless you wired real backends."
echo "  - Run through docs/golden-path.md for wallet-scoped keys and billing rehearsal."

exit "$fail"
