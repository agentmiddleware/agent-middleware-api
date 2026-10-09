#!/usr/bin/env sh
# Build a self-contained deploy directory for the refund partner fixture.
#
# The fixture lives in tests/support/, which .dockerignore excludes, and it must
# not ship in the production image. This copies it into a standalone directory
# that `railway up` can upload on its own. See docs/refund-partner-staging.md.
#
# Usage: scripts/build_refund_partner_bundle.sh [output-dir]
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
out_dir="${1:-${TMPDIR:-/tmp}/refund-partner-bundle}"
# Strip trailing slashes so the safety comparisons below are exact.
out_dir="${out_dir%/}"

# Never delete whatever path is given: refuse filesystem roots, the user's
# home, the shared temp root itself, the repo, and any directory containing it.
tmp_root="${TMPDIR:-/tmp}"
tmp_root="${tmp_root%/}"
case "$out_dir" in
  ""|"/"|"."|"..")
    echo "refusing to clear output dir '$out_dir'" >&2
    exit 1
    ;;
esac
if [ -n "${HOME:-}" ] && [ "$out_dir" = "$HOME" ]; then
  echo "refusing to clear home directory '$out_dir'" >&2
  exit 1
fi
if [ "$out_dir" = "$tmp_root" ] || [ "$out_dir" = "$repo_root" ]; then
  echo "refusing to clear protected directory '$out_dir'" >&2
  exit 1
fi
case "$repo_root" in
  "$out_dir"/*)
    echo "refusing to clear '$out_dir': it contains the repository" >&2
    exit 1
    ;;
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
