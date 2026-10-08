#!/usr/bin/env bash
# Clean-room install smoke test for the b2a-sdk Python package.
#
# Builds the wheel and sdist from ./b2a_sdk, installs each artifact into a
# fresh virtualenv, and checks the installed package imports, reports the
# version from b2a_sdk/pyproject.toml, and exposes the verify CLI entry
# point. Temporary build output and virtualenvs live under mktemp and are
# removed on exit; the project .venv is never touched.
#
# Usage:
#   scripts/sdk_install_smoke.sh [--wheel-only | --sdist-only] [--with-verify]
#
# --with-verify also installs the `verify` extra (cryptography) and runs one
# offline bundle verification through the installed CLI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="all"
WITH_VERIFY=0

for arg in "$@"; do
  case "$arg" in
    --wheel-only) ARTIFACT="wheel" ;;
    --sdist-only) ARTIFACT="sdist" ;;
    --with-verify) WITH_VERIFY=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null 2>&1 || { echo "uv is required on PATH" >&2; exit 2; }

SDK_VERSION="$(grep -E '^version = "' "$ROOT/b2a_sdk/pyproject.toml" | head -1 | cut -d'"' -f2)"
if [ -z "$SDK_VERSION" ]; then echo "could not parse SDK version" >&2; exit 1; fi
echo "SDK version: $SDK_VERSION"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

uv build "$ROOT/b2a_sdk" --out-dir "$WORK/dist" --quiet
WHEEL="$WORK/dist/b2a_sdk-${SDK_VERSION}-py3-none-any.whl"
SDIST="$WORK/dist/b2a_sdk-${SDK_VERSION}.tar.gz"
[ -f "$WHEEL" ] || { echo "wheel missing: $WHEEL" >&2; exit 1; }
[ -f "$SDIST" ] || { echo "sdist missing: $SDIST" >&2; exit 1; }
echo "built: $(basename "$WHEEL") $(basename "$SDIST")"

uvx twine check "$WORK"/dist/*

smoke_one() {
  local artifact="$1"
  local label="$2"
  local venv="$WORK/smoke-$label"
  uv venv "$venv" --quiet
  if [ "$WITH_VERIFY" -eq 1 ]; then
    uv pip install --python "$venv/bin/python" --quiet "${artifact}[verify]"
  else
    uv pip install --python "$venv/bin/python" --quiet "$artifact"
  fi
  # Run from $WORK so the repo checkout can never shadow the installed package.
  cd "$WORK"
  "$venv/bin/python" -c "import b2a_sdk; assert b2a_sdk.__version__ == '$SDK_VERSION', b2a_sdk.__version__"
  "$venv/bin/python" -c "from b2a_sdk import AgentMiddlewareClient, verify_bundle, parse_402_response"
  "$venv/bin/b2a-verify-receipt" --help >/dev/null
  echo "smoke $label: import, version $SDK_VERSION, CLI entry point OK"
  cd "$ROOT"
}

if [ "$ARTIFACT" = "all" ] || [ "$ARTIFACT" = "wheel" ]; then
  smoke_one "$WHEEL" "wheel"
fi
if [ "$ARTIFACT" = "all" ] || [ "$ARTIFACT" = "sdist" ]; then
  smoke_one "$SDIST" "sdist"
fi

echo "install smoke passed for b2a-sdk $SDK_VERSION"
