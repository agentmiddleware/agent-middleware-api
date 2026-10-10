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
out_dir="${1-${TMPDIR:-/tmp}/refund-partner-bundle}"

refuse() {
  echo "build_refund_partner_bundle: refusing to delete unsafe path: $1" >&2
  exit 2
}

# Only replace the named bundle directory directly under /tmp or TMPDIR.
# Resolve symlinks and .. even when the target does not exist yet, then delete
# the checked path.
if ! out_canonical="$(python3 - "$out_dir" "${TMPDIR:-/tmp}" "$repo_root" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1]).resolve()
roots = {Path("/tmp").resolve(), Path(sys.argv[2]).resolve()}
blocked = {Path("/"), Path.home().resolve(), Path(sys.argv[3]).resolve()}
allowed = {root / "refund-partner-bundle" for root in roots - blocked}
if target not in allowed:
    raise SystemExit(2)
print(target)
PY
)"; then
  refuse "$out_dir"
fi
out_dir="$out_canonical"

rm -rf -- "$out_dir"
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
