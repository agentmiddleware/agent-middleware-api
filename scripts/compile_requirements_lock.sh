#!/usr/bin/env bash
# Regenerate the hashed dependency lock from requirements.txt.
#
# requirements.txt stays the human-edited input (lower bounds). The lock
# pins every package with hashes so installs are reproducible.
# Run from the repo root after editing requirements.txt:
#   scripts/compile_requirements_lock.sh
set -euo pipefail
cd "$(dirname "$0")/.."
uv pip compile requirements.txt \
  --generate-hashes \
  --python-version 3.12 \
  -o requirements.lock
echo "Wrote requirements.lock from requirements.txt"
