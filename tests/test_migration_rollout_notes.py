"""Every schema migration from 040 onward must ship a rollout note.

Production boot refuses to start when the database's Alembic revision differs
from the packaged head in either direction. Applying a new migration therefore
retires the previously serving image: it can no longer restart against the
upgraded database. Migration 040 crossed that boundary without a plan and
needed a same-night compatibility release, recorded in
docs/schema-040-rollout.md. This test turns that lesson into a merge
requirement: a migration lands together with a note that names its revision
and states its rollback boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "versions"
DOCS_DIR = REPO_ROOT / "docs"
FIRST_GATED_REVISION = 40


def _gated_migrations() -> list[Path]:
    paths = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.py"))
    return [path for path in paths if int(path.name[:3]) >= FIRST_GATED_REVISION]


def _note_for(path: Path) -> Path:
    return DOCS_DIR / f"schema-{int(path.name[:3]):03d}-rollout.md"


def test_gate_covers_migration_040() -> None:
    names = [path.name for path in _gated_migrations()]
    assert any(name.startswith("040_") for name in names), names


@pytest.mark.parametrize(
    "migration", _gated_migrations(), ids=lambda path: path.stem
)
def test_migration_ships_a_rollout_note(migration: Path) -> None:
    note = _note_for(migration)
    assert note.exists(), (
        f"{migration.name} has no rollout note. Add {note.relative_to(REPO_ROOT)} "
        "stating the compatibility release that precedes it and the rollback "
        "boundary it creates; see docs/schema-040-rollout.md for the shape."
    )
    text = note.read_text(encoding="utf-8")
    revision = migration.stem
    assert revision in text, (
        f"{note.relative_to(REPO_ROOT)} must name the revision {revision}"
    )
    assert "rollback" in text.lower(), (
        f"{note.relative_to(REPO_ROOT)} must state the rollback boundary"
    )
