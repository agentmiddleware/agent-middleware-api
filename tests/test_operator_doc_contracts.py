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


def test_local_demo_uses_supported_persistent_quickstart():
    text = (DOCS / "demo-instance.md").read_text()
    section = text.split("## Option 2:", 1)[1].split("## Demo API Keys", 1)[0]
    assert "make quickstart" in section
    assert "database" in section and "signing seed" in section
    assert "data/quickstart/" in section
    assert "./demo.db:/app/demo.db" not in section
