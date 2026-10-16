#!/usr/bin/env bash
# Prints the git revision range the CI secret scan must cover
# (.github/workflows/ci.yml secret_scan). Kept in a script so the range
# selection is exercised by tests/test_secret_scan_range.py, not only by CI.
#
# Inputs (environment): EVENT_NAME, PR_BASE_SHA, PR_HEAD_SHA,
# PUSH_BEFORE_SHA, PUSH_SHA. Optional SECRET_SCAN_VERIFIED_BASE overrides the
# pinned fallback base (tests use it; CI must not).
set -euo pipefail

# Last main commit whose full ancestry is known clean: #811, the commit that
# introduced the commit-range scan. Everything after it on main was merged
# through a PR whose range was scanned; everything before it was covered by
# the full-history verification recorded in .gitleaks.toml. Move this forward
# only after a full-history scan of the new commit passes.
VERIFIED_BASE="${SECRET_SCAN_VERIFIED_BASE:-dd16051192acd72625ea9472c2a6802a497c5b4a}"
ZERO_SHA="0000000000000000000000000000000000000000"

has_commit() {
  git cat-file -e "${1}^{commit}" 2>/dev/null
}

if [ "${EVENT_NAME:-}" = "pull_request" ]; then
  echo "${PR_BASE_SHA}..${PR_HEAD_SHA}"
  exit 0
fi

: "${PUSH_SHA:?PUSH_SHA is required for push events}"
before="${PUSH_BEFORE_SHA:-}"

if [ -n "$before" ] && [ "$before" != "$ZERO_SHA" ]; then
  # A force push leaves the old tip unreachable from any ref, so the
  # full-history checkout does not contain it. GitHub still serves it by SHA
  # until it is garbage-collected; try once before falling back.
  if ! has_commit "$before"; then
    git fetch --no-tags --quiet origin "$before" >/dev/null 2>&1 || true
  fi
  if has_commit "$before"; then
    echo "${before}..${PUSH_SHA}"
    exit 0
  fi
fi

# No usable push base (branch creation, or a force push whose old tip is
# gone). This job only runs for pushes to main, so "commits not on main" is
# always empty; scan everything since the last verified-clean commit instead.
# If the push rewrote history below that commit, the range would silently
# skip the rewritten commits — fail closed and make a human re-verify.
if ! has_commit "$VERIFIED_BASE" \
  || ! git merge-base --is-ancestor "$VERIFIED_BASE" "$PUSH_SHA"; then
  echo "::error::Secret-scan base ${VERIFIED_BASE} is not an ancestor of ${PUSH_SHA}; history was rewritten below the verified point. Run a full-history gitleaks scan and move VERIFIED_BASE in scripts/secret_scan_range.sh." >&2
  exit 1
fi
echo "${VERIFIED_BASE}..${PUSH_SHA}"
