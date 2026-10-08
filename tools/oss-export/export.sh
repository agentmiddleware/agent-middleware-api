#!/usr/bin/env bash
# Curated export from the private repo into the public-candidate layout.
set -euo pipefail
SRC=~/tmp/amw-oss/src
DST=~/tmp/amw-oss/agent-middleware
X=(--exclude __pycache__ --exclude '*.pyc' --exclude .pytest_cache --exclude node_modules --exclude '*.db' --exclude .DS_Store --exclude dist)
G=$DST/gateway
mkdir -p $G $DST/sdk $DST/integrations $DST/examples $DST/spec $DST/verifier
# --- gateway (FSL) ---
rsync -a "${X[@]}" $SRC/app $SRC/migrations $SRC/tests $SRC/failure_lab $SRC/static $G/
rsync -a "${X[@]}" \
  --exclude railway_preflight.py --exclude prepare_railway_release.py --exclude auto_pr_runner.py \
  --exclude publish_live_proof.py --exclude repo_guardian.py --exclude record_site_transcript.py \
  --exclude operator_analytics_export.py \
  $SRC/scripts $G/
for f in alembic.ini Dockerfile Dockerfile.dev docker-compose.yml Makefile requirements.txt pyproject.toml mypy.ini ruff.toml .env.example .dockerignore TROUBLESHOOTING.md DEMO_SCRIPT.md; do cp $SRC/$f $G/; done
mkdir -p $G/docs
for d in threat-model.md owasp-agentic-top10-mapping.md security-review-kit.md failure-semantics.md failure-lab.md failure-lab-suite.md key-management.md quickstart.md golden-path.md signed-quotes.md permit-requests.md denial-details.md human-approval-gate.md tool-interface-authority.md mcp-tool-metadata-spec.md POLICY_ENFORCEMENT.md PROOF_MATRIX.md PROOF_SURFACES.md static-dev-api-keys.md stranger-test.md related-work.md partner-api-key-bootstrap.md schema-040-rollout.md schema-041-rollout.md schema-042-rollout.md human-onboarding.md agent-accountability.md agent-self-credentialing.md awi-adoption-guide.md awi-action-vocabulary-spec.md partner-first-tool-runbook.md openapi.json agent-recipes.md authority-required-flow.md constant-test-loop.md settlement-rails.md simulations-inventory.md sim-inventory.json invariant-attack-report.md demo-trust-plane-output.md README.md; do [ -e $SRC/docs/$d ] && cp $SRC/docs/$d $G/docs/ || echo "missing doc $d"; done
# --- root trust docs ---
cp $SRC/SECURITY_LIMITATIONS.md $SRC/TRUST_MODEL.md $DST/
# --- SDKs (Apache) ---
rsync -a "${X[@]}" $SRC/b2a_sdk/ $DST/sdk/python/
# --- integrations (Apache) ---
for w in $SRC/wrappers/*/; do rsync -a "${X[@]}" $w $DST/integrations/$(basename $w)/; done
rsync -a "${X[@]}" $SRC/framework_integrations/ $DST/integrations/framework_integrations/
# --- examples (Apache) ---
rsync -a "${X[@]}" $SRC/examples/ $DST/examples/
# drop old MIT license files; replaced by Apache below
find $DST/sdk $DST/integrations $DST/examples -name LICENSE -delete
