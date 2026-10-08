#!/usr/bin/env bash
# Build a self-contained deploy directory for the refund partner fixture.
#
# The fixture lives in tests/support/, which .dockerignore excludes, and it must
# not ship in the production image. This copies it into a standalone directory
# that `railway up` can upload on its own. See docs/refund-partner-staging.md.
#
# Usage: scripts/build_refund_partner_bundle.sh [output-dir]
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
out_dir="${1:-${TMPDIR:-/tmp}/refund-partner-bundle}"

refuse() {
  echo "build_refund_partner_bundle: refusing to delete unsafe path: $1" >&2
  exit 2
}

if [ -z "${out_dir:-}" ]; then
  refuse "(empty path)"
fi

# Canonicalize for the safety checks below. realpath -m resolves .. and
# symlinks without requiring the path to exist (GNU coreutils); elsewhere
# fall back to making the path absolute so the exact-match checks still hold.
if out_canonical="$(realpath -m "$out_dir" 2>/dev/null)"; then
  :
else
  case "$out_dir" in
    /*) out_canonical="$out_dir" ;;
    *) out_canonical="$PWD/$out_dir" ;;
  esac
fi
# Strip trailing slashes for comparison ("/" becomes the empty string).
out_stripped="${out_canonical%/}"

home_dir="${HOME:-}"
tmp_dir="${TMPDIR:-/tmp}"
tmp_stripped="${tmp_dir%/}"

if [ -z "$out_stripped" ]; then
  refuse "$out_dir (resolves to filesystem root)"
fi
if [ "$out_stripped" = "$repo_root" ]; then
  refuse "$out_dir (the repo root)"
fi
if [ -n "$home_dir" ] && [ "$out_stripped" = "$home_dir" ]; then
  refuse "$out_dir (home directory)"
fi
if [ -n "$tmp_stripped" ] && [ "$out_stripped" = "$tmp_stripped" ]; then
  refuse "$out_dir (the temp directory itself)"
fi
# Never delete a top-level directory such as /tmp or /data.
case "$out_stripped" in
  /*/*) ;;
  *) refuse "$out_dir (top-level directory)" ;;
esac

rm -rf "$out_dir"
mkdir -p "$out_dir"

cp "$repo_root/tests/support/mcp_refund_partner_app.py" "$out_dir/main.py"

cat > "$out_dir/requirements.txt" <<'EOF'
mcp>=1.29.0,<2
uvicorn[standard]>=0.53.0
EOF

cat > "$out_dir/railway.json" <<'EOF'
{
  "$schema": "https://railway.com/railway.schema.json",
  "deploy": {
    "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE"
  }
}
EOF

echo "refund partner bundle written to $out_dir"
