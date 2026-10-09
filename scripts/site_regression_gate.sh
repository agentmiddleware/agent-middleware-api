#!/usr/bin/env bash
# Site regression gate: run every browser regression script to completion and
# report each one separately, instead of stopping at the first failure.
#
# Usage:
#   scripts/site_regression_gate.sh [preview-url]
#
# With no URL this builds the site into a fresh temporary directory with
# placeholder launch contacts, serves it on loopback, runs the three
# regression scripts against it, then tears the server down. With a URL it
# runs the two browser scripts against that preview and the arcade script
# without any server. Only loopback URLs are accepted.
#
# Environment:
#   PLAYWRIGHT_PATH   optional path to an installed Playwright module
#   SCREENSHOT_DIR    optional directory for the scripts' screenshots
#   SITE_GATE_NO_SERVE=1  run the scripts without building or serving a
#                     preview (used to exercise this runner's own reporting)
#   SITE_GATE_TESTS_DIR   directory holding the three check scripts
#                     (default: tests)
#
# Exit status is 0 only when every script passes. A missing browser driver
# fails the gate instead of silently skipping the browser checks.

set -u

TESTS_DIR="${SITE_GATE_TESTS_DIR:-tests}"
PREVIEW_URL="${1:-${SITE_PREVIEW_URL:-}}"
PLAYWRIGHT_PATH="${PLAYWRIGHT_PATH:-}"
SCREENSHOT_DIR="${SCREENSHOT_DIR:-}"
NO_SERVE="${SITE_GATE_NO_SERVE:-}"

ARCADE_SCRIPT="$TESTS_DIR/test_arcade_regressions.mjs"
DESIGN_SCRIPT="$TESTS_DIR/test_site_design.mjs"
PILOT_SCRIPT="$TESTS_DIR/test_site_pilot_fit.mjs"

SERVER_PID=""
SERVE_DIR=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  if [ -n "$SERVE_DIR" ]; then
    rm -rf "$SERVE_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# The builder rejects reserved and example domains, so the throwaway preview
# uses the same routable placeholder contacts as the site contract tests.
PLACEHOLDER_NAME="Design Partner Labs LLC"
PLACEHOLDER_EMAIL="operator@design-partner-labs.org"

PORT="${SITE_PREVIEW_PORT:-8765}"

if [ -z "$PREVIEW_URL" ] && [ -z "$NO_SERVE" ]; then
  SERVE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/site-preview-XXXXXX")/dist"
  PUBLIC_DISPLAY_NAME="$PLACEHOLDER_NAME" \
  PUBLIC_CONTACT_EMAIL="$PLACEHOLDER_EMAIL" \
  python3 site/build_site.py --output "$SERVE_DIR" || {
    echo "FAIL  site build (preview not built, browser checks cannot run)"
    exit 1
  }
  python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SERVE_DIR" >/dev/null 2>&1 &
  SERVER_PID="$!"
  PREVIEW_URL="http://127.0.0.1:$PORT"
  for _ in $(seq 1 50); do
    if python3 -c "import sys, urllib.request; urllib.request.urlopen('$PREVIEW_URL/', timeout=1).read(1)" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
fi

case "$PREVIEW_URL" in
  http://127.0.0.1*|http://localhost*|http://\[::1\]*) ;;
  "") ;;
  *)
    echo "FAIL  refusing non-loopback preview URL: $PREVIEW_URL"
    exit 1
    ;;
esac

pass_count=0
fail_count=0
report=""

run_script() {
  name="$1"
  shift
  output="$("$@" 2>&1)"
  status="$?"
  printf '%s\n' "$output"
  if [ "$status" -eq 0 ]; then
    pass_count=$((pass_count + 1))
    report="$report
PASS  $name"
  else
    fail_count=$((fail_count + 1))
    report="$report
FAIL  $name (exit $status)"
  fi
}

echo "--- $ARCADE_SCRIPT (no server, no browser) ---"
run_script "arcade regressions (node --test)" node --test "$ARCADE_SCRIPT"

for script in "$DESIGN_SCRIPT" "$PILOT_SCRIPT"; do
  echo "--- $script ${PREVIEW_URL:-(no preview URL: script falls back to its default)} ---"
  if [ -n "$PLAYWRIGHT_PATH" ] && [ -n "$SCREENSHOT_DIR" ]; then
    run_script "$script" node "$script" "$PREVIEW_URL" "$PLAYWRIGHT_PATH" "$SCREENSHOT_DIR"
  elif [ -n "$PLAYWRIGHT_PATH" ]; then
    run_script "$script" node "$script" "$PREVIEW_URL" "$PLAYWRIGHT_PATH"
  else
    run_script "$script" node "$script" "$PREVIEW_URL"
  fi
done

echo
echo "Site regression gate: $pass_count passed, $fail_count failed.$report"

if [ "$fail_count" -gt 0 ]; then
  exit 1
fi
