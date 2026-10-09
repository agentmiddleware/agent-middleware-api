#!/usr/bin/env sh
# Build a self-contained deploy directory for the refund partner fixture.
#
# The fixture lives in tests/support/, which .dockerignore excludes, and it must
# not ship in the production image. This copies it into a standalone directory
# that `railway up` can upload on its own. See docs/refund-partner-staging.md.
#
# Usage: scripts/build_refund_partner_bundle.sh [output-dir]
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd -P)"
out_dir="${1:-${TMPDIR:-/tmp}/refund-partner-bundle}"

# Never delete whatever path is given: refuse filesystem roots, the user's
# home, the shared temp root itself, the repo, and any directory containing it.
# Compare canonical absolute paths so un-normalized spellings (doubled
# slashes, dot segments, trailing slashes, symlinks) cannot dodge the checks.
if [ -z "$out_dir" ]; then
  echo "refusing to clear output dir '$out_dir'" >&2
  exit 1
fi
case "$out_dir" in
  /*) out_dir_abs="$out_dir" ;;
  *) out_dir_abs="$(pwd)/$out_dir" ;;
esac
case "$out_dir_abs" in
  *'//'*|*'/./'*|*'/../'*)
    echo "refusing to clear output dir '$out_dir': un-normalized path" >&2
    exit 1
    ;;
esac
case "$out_dir_abs" in
  */.|*/..|*/./|*/../)
    echo "refusing to clear output dir '$out_dir': un-normalized path" >&2
    exit 1
    ;;
esac
# Strip ALL trailing slashes (keeping "/" itself) so comparisons are exact.
while [ "$out_dir_abs" != "/" ] && [ "${out_dir_abs%/}" != "$out_dir_abs" ]; do
  out_dir_abs="${out_dir_abs%/}"
done
# Resolve symlinks and dot segments for paths that already exist.
if resolved="$(cd "$out_dir_abs" 2>/dev/null && pwd -P)"; then
  out_dir_abs="$resolved"
fi
# Never replace an existing non-directory (regular file, symlink to a file,
# and similar): rm -rf would delete it and mkdir would leave a directory
# behind, which is data loss outside the documented bundle behavior.
if [ -e "$out_dir_abs" ] || [ -L "$out_dir_abs" ]; then
  if [ ! -d "$out_dir_abs" ]; then
    echo "refusing to clear output dir '$out_dir': not a directory" >&2
    exit 1
  fi
fi
tmp_root="${TMPDIR:-/tmp}"
while [ "$tmp_root" != "/" ] && [ "${tmp_root%/}" != "$tmp_root" ]; do
  tmp_root="${tmp_root%/}"
done
if resolved="$(cd "$tmp_root" 2>/dev/null && pwd -P)"; then
  tmp_root="$resolved"
fi
home_dir="${HOME:-}"
while [ -n "$home_dir" ] && [ "$home_dir" != "/" ] && [ "${home_dir%/}" != "$home_dir" ]; do
  home_dir="${home_dir%/}"
done
if [ -n "$home_dir" ] && resolved="$(cd "$home_dir" 2>/dev/null && pwd -P)"; then
  home_dir="$resolved"
fi
case "$out_dir_abs" in
  ""|"/"|"."|"..")
    echo "refusing to clear output dir '$out_dir'" >&2
    exit 1
    ;;
esac
if [ -n "$home_dir" ] && [ "$out_dir_abs" = "$home_dir" ]; then
  echo "refusing to clear home directory '$out_dir'" >&2
  exit 1
fi
if [ "$out_dir_abs" = "$tmp_root" ] || [ "$out_dir_abs" = "$repo_root" ]; then
  echo "refusing to clear protected directory '$out_dir'" >&2
  exit 1
fi
case "$repo_root" in
  "$out_dir_abs"/*)
    echo "refusing to clear '$out_dir': it contains the repository" >&2
    exit 1
    ;;
esac

out_dir="$out_dir_abs"
rm -rf -- "$out_dir"
mkdir -p -- "$out_dir"

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
