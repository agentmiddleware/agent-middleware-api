"""Migration 033 drops a table irreversibly; that must be written down.

The upgrade deletes `optimizer_telemetry` data by design, while the downgrade
only recreates the empty table schema. Without an explicit note, an operator
could run the downgrade as a rollback expecting recovery that cannot happen.
These tests require the irreversibility to be documented both in the
downgrade notes of the migration module and in the operations runbook.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "migrations" / "versions" / "033_drop_optimizer_telemetry.py"
RUNBOOK = REPO_ROOT / "docs" / "partner-first-tool-runbook.md"


def _downgrade_notes() -> str:
    module = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            return ast.get_docstring(node) or ""
    raise AssertionError("033 migration defines no downgrade() function")


def test_downgrade_documents_irreversibility() -> None:
    notes = _downgrade_notes().lower()
    assert "irreversib" in notes, "033 downgrade() must state that it is irreversible"
    assert "empty" in notes, (
        "033 downgrade() must state that it recreates the empty table"
    )
    assert "restor" in notes or "recover" in notes, (
        "033 downgrade() must state that dropped rows are not restored"
    )


def test_runbook_documents_033_irreversibility() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "033" in text, "runbook must still discuss revision 033"
    lowered = text.lower()
    assert "irreversib" in lowered, (
        "runbook must state that the 033 drop is irreversible"
    )
    assert "restores no" in lowered or "restores no rows" in lowered, (
        "runbook must state that the 033 downgrade restores no rows"
    )
