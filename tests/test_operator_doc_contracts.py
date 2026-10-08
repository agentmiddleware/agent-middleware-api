"""Operator recipes must preserve the current release and schema boundaries."""

from pathlib import Path

import pytest


DOCS = Path(__file__).resolve().parents[1] / "docs"


@pytest.mark.parametrize("name", ["deploy-railway.md", "human-onboarding.md"])
def test_legacy_database_guidance_requires_schema_and_data_review(name):
    text = (DOCS / name).read_text()
    assert "manual review" in text
    assert "schema and data-migration history" in text
    assert "proven matching historical revision" in text
    assert "run `alembic stamp head` once" not in text
    assert "run **`alembic stamp head`** once" not in text


def test_lockdown_uses_canonical_release_context():
    text = (DOCS / "deploy-railway.md").read_text()
    section = text.split("## Applying the Narrow lockdown", 1)[1].split(
        "## Preflight", 1
    )[0]
    assert "#canonical-deploy-path" in section
    assert "GitHub → Railway integration if" not in section


def test_rotation_requires_schema_compatible_release_before_key_change():
    text = (DOCS / "api-key-rotation.md").read_text()
    section = text.split("## Rotation procedure", 1)[1].split(
        "## Post-rotation audit", 1
    )[0]
    assert "schema-compatible" in section
    assert "exact-SHA" in section
    assert "schema-042-rollout.md" in section
    assert "clicking **Redeploy**" not in section
    assert "Deploy to Railway workflow" not in section


def test_deploy_minimal_path_links_into_detail():
    text = (DOCS / "deploy-railway.md").read_text()
    section = text.split("## Minimal path", 1)[1].split("## Managed", 1)[0]
    for anchor in (
        "#required-production-variables",
        "#canonical-deploy-path",
        "#preflight--before-you-ship",
        "#after-deploy--verify",
    ):
        assert anchor in section, anchor


def test_human_approval_gate_states_pilot_prerequisites():
    text = (DOCS / "human-approval-gate.md").read_text()
    section = text.split("## Pilot prerequisites", 1)[1].split("## What it does", 1)[0]
    assert "SENTINEL_API_URL" in section
    assert "SENTINEL_API_KEY" in section
    assert "SIMULATION_MODE_HUMAN_APPROVAL=false" in section
    assert "human_approval_unavailable" in section


@pytest.mark.parametrize(
    "name", ["mcp-registry-submission.md", "agentmarket-submission.md"]
)
def test_registry_docs_carry_preflight_status(name):
    text = (DOCS / name).read_text().lower()
    assert "preflight status" in text
    assert "public contact monitored" in text
    assert "endpoint enabled" in text
    assert "preflight passed" in text


def test_local_demo_uses_supported_persistent_quickstart():
    text = (DOCS / "demo-instance.md").read_text()
    section = text.split("## Option 2:", 1)[1].split("## Demo API Keys", 1)[0]
    assert "make quickstart" in section
    assert "database" in section and "signing seed" in section
    assert "data/quickstart/" in section
    assert "./demo.db:/app/demo.db" not in section
