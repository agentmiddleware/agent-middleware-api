#!/usr/bin/env bash
# Curated export from the source repo into the public-candidate layout.
set -euo pipefail
SRC=${AMW_EXPORT_SRC:-$HOME/tmp/amw-oss/src}
DST=${AMW_EXPORT_DST:-$HOME/tmp/amw-oss/agent-middleware}
if [[ ! -e "$DST/.git" ]]; then
  echo "export destination must be a Git working copy: $DST" >&2
  exit 1
fi
X=(--filter='H __pycache__' --filter='H *.pyc' --filter='H .pytest_cache' --filter='H node_modules' --filter='H *.db' --filter='H .DS_Store' --filter='H dist')
G=$DST/gateway
if [[ ! -f "$G/LICENSE.md" ]]; then
  echo "export destination is missing gateway/LICENSE.md (FSL-1.1-ALv2)" >&2
  exit 1
fi
mkdir -p "$G" "$DST/sdk" "$DST/integrations" "$DST/examples" "$DST/spec" "$DST/verifier"
# --- gateway (FSL) ---
for d in app migrations failure_lab static; do
  rsync -a --delete "${X[@]}" "$SRC/$d/" "$G/$d/"
done
rsync -a --delete --delete-excluded "${X[@]}" \
  --exclude test_prepare_railway_release.py --exclude test_publish_live_proof.py \
  --exclude test_repo_guardian.py --exclude test_auto_pr_runner.py \
  --exclude test_railway_preflight.py --exclude test_onboarding_contract.py \
  --exclude test_site_agent_interface.py --exclude test_acta_receipt_interop.py \
  --exclude test_oss_export.py \
  "$SRC/tests/" "$G/tests/"
rsync -a --delete --delete-excluded "${X[@]}" \
  --exclude railway_preflight.py --exclude prepare_railway_release.py --exclude auto_pr_runner.py \
  --exclude publish_live_proof.py --exclude repo_guardian.py --exclude record_site_transcript.py \
  --exclude operator_analytics_export.py \
  "$SRC/scripts/" "$G/scripts/"
for f in alembic.ini Dockerfile Dockerfile.dev docker-compose.yml Makefile requirements.txt pyproject.toml mypy.ini ruff.toml .env.example .dockerignore TROUBLESHOOTING.md DEMO_SCRIPT.md WEDGE.md DESIGN_PARTNER_GUIDE.md; do cp "$SRC/$f" "$G/"; done
python3 - "$G/pyproject.toml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
private_license = 'license = "BUSL-1.1"'
if text.count(private_license) != 1:
    raise SystemExit("expected one private license field in gateway pyproject.toml")
path.write_text(text.replace(private_license, 'license = "LicenseRef-FSL-1.1-ALv2"'))
PY
python3 - "$G" <<'PY'
from pathlib import Path
import sys

gateway = Path(sys.argv[1])
for name in ("Dockerfile", "Dockerfile.dev"):
    path = gateway / name
    text = path.read_text()
    edits = {
        "COPY requirements.txt .": "COPY gateway/requirements.txt .\nCOPY sdk/python/ /sdk/python/",
        "RUN pip install --no-cache-dir -r requirements.txt": (
            "RUN pip install --no-cache-dir -r requirements.txt "
            "&& pip install --no-cache-dir /sdk/python"
        ),
        "COPY . .": "COPY gateway/ .",
    }
    if name == "Dockerfile":
        edits["COPY .build_commit_sha /app/.build_commit_sha"] = (
            "COPY gateway/.build_commit_sha /app/.build_commit_sha"
        )
    for old, new in edits.items():
        if text.count(old) != 1:
            raise SystemExit(f"expected one {old!r} in {path}")
        text = text.replace(old, new)
    path.write_text("# Build from the public repository root with -f gateway/" + name + ".\n" + text)

compose = gateway / "docker-compose.yml"
text = compose.read_text()
old = "      context: .\n      dockerfile: Dockerfile.dev"
if text.count(old) != 1:
    raise SystemExit("expected gateway-local Docker build context in docker-compose.yml")
compose.write_text(text.replace(old, "      context: ..\n      dockerfile: gateway/Dockerfile.dev"))
PY
cp "$SRC/.dockerignore" "$DST/.dockerignore"
rm -rf "$G/docs"
mkdir -p "$G/docs"
for d in threat-model.md owasp-agentic-top10-mapping.md security-review-kit.md failure-semantics.md failure-lab.md failure-lab-suite.md key-management.md quickstart.md golden-path.md signed-quotes.md permit-requests.md denial-details.md human-approval-gate.md tool-interface-authority.md mcp-tool-metadata-spec.md POLICY_ENFORCEMENT.md PROOF_MATRIX.md PROOF_SURFACES.md static-dev-api-keys.md stranger-test.md related-work.md partner-api-key-bootstrap.md schema-040-rollout.md schema-041-rollout.md schema-042-rollout.md human-onboarding.md agent-accountability.md agent-self-credentialing.md awi-adoption-guide.md awi-action-vocabulary-spec.md partner-first-tool-runbook.md openapi.json agent-recipes.md authority-required-flow.md constant-test-loop.md settlement-rails.md simulations-inventory.md sim-inventory.json invariant-attack-report.md demo-trust-plane-output.md README.md; do [ -e "$SRC/docs/$d" ] && cp "$SRC/docs/$d" "$G/docs/" || echo "missing doc $d"; done
python3 - "$G/docs/quickstart.md" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
clone = r"git clone https://github\.com/[^/\s]+/agent-middleware-api\.git\ncd agent-middleware-api\nmake quickstart"
if len(re.findall(clone, text)) != 1:
    raise SystemExit("expected one source checkout command in quickstart.md")
text = re.sub(clone, "cd gateway\nmake quickstart", text)
edits = {
    "# Quickstart: from `git clone` to a verified receipt": "# Quickstart: from checkout to a verified receipt",
    "## 1. Boot the trust plane (~2 minutes)\n\n": (
        "## 1. Boot the trust plane (~2 minutes)\n\n"
        "From the root of your `agent-middleware` export checkout:\n\n"
    ),
    "repository root:\n": "`gateway/` directory:\n",
    "PYTHONPATH=b2a_sdk/src": "PYTHONPATH=../sdk/python/src",
}
for old, new in edits.items():
    if old not in text:
        raise SystemExit(f"expected {old!r} in quickstart.md")
    text = text.replace(old, new)
path.write_text(text)
PY
# --- root trust docs ---
cp "$SRC/SECURITY_LIMITATIONS.md" "$SRC/TRUST_MODEL.md" "$DST/"
# --- SDKs (Apache) ---
rsync -a --delete "${X[@]}" --filter='P LICENSE' --filter='H LICENSE' "$SRC/b2a_sdk/" "$DST/sdk/python/"
# --- integrations (Apache) ---
for w in "$SRC"/wrappers/*/; do rsync -a --delete "${X[@]}" --filter='P LICENSE' --filter='H LICENSE' "$w" "$DST/integrations/$(basename "$w")/"; done
rsync -a --delete "${X[@]}" --filter='P LICENSE' --filter='H LICENSE' "$SRC/framework_integrations/" "$DST/integrations/framework_integrations/"
python3 - "$DST" <<'PY'
from pathlib import Path
import sys

destination = Path(sys.argv[1])
sdk = destination / "sdk/python/pyproject.toml"
configs = [sdk, *sorted((destination / "integrations").glob("*/pyproject.toml"))]
for path in configs:
    text = path.read_text()
    private_license = 'license = "MIT"'
    if text.count(private_license) != 1:
        raise SystemExit(f"expected one MIT license field in {path}")
    text = text.replace(private_license, 'license = "Apache-2.0"')
    if path == sdk:
        private_classifier = '"License :: OSI Approved :: MIT License"'
        if text.count(private_classifier) != 1:
            raise SystemExit("expected one MIT classifier in SDK pyproject.toml")
        text = text.replace(
            private_classifier, '"License :: OSI Approved :: Apache Software License"'
        )
    path.write_text(text)
PY
# --- examples (Apache) ---
rsync -a --delete "${X[@]}" --filter='P LICENSE' --filter='H LICENSE' "$SRC/examples/" "$DST/examples/"
