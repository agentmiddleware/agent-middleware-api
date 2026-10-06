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
