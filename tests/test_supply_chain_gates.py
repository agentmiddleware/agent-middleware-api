"""Guards for dependency-update and gate-scope coverage.

Audit finding (2026-10): Dependabot covered pip and GitHub Actions only, so
the pinned Node dependency in .railway/package.json went stale silently;
the ruff and mypy configs enforce a narrow rule set without saying so. These
tests pin the fixes: npm coverage for .railway, and the narrow gate scope
documented as deliberate inside the configs themselves.

Each check is written against a helper that also runs over a synthetic
pre-fix input, so a gate that only ever passes is not trusted blindly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT_PATH = ROOT / ".github" / "dependabot.yml"
RAILWAY_DIR = ROOT / ".railway"
RUFF_PATH = ROOT / "ruff.toml"
MYPY_PATH = ROOT / "mypy.ini"

RAILWAY_NPM_DIRECTORY = "/.railway"


def _npm_directories(config: dict[str, Any]) -> list[str]:
    """Return the directories of every npm update entry in a config."""
    directories = []
    updates = config.get("updates", [])
    if not isinstance(updates, list):
        return directories
    for entry in updates:
        if not isinstance(entry, dict):
            continue
        if entry.get("package-ecosystem") == "npm" and entry.get("directory"):
            directories.append(entry["directory"])
    return directories


def _npm_entry_has_schedule(config: dict[str, Any], directory: str) -> bool:
    updates = config.get("updates", [])
    if not isinstance(updates, list):
        return False
    for entry in updates:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("package-ecosystem") == "npm"
            and entry.get("directory") == directory
            and isinstance(entry.get("schedule"), dict)
            and entry["schedule"].get("interval")
        ):
            return True
    return False


def _load_dependabot() -> dict[str, Any]:
    with DEPENDABOT_PATH.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    assert isinstance(config, dict), ".github/dependabot.yml must parse to a mapping"
    return config


def test_npm_directories_detects_a_missing_railway_entry():
    """The helper must report nothing for the pre-fix, pip+Actions-only file."""
    pre_fix = {
        "version": 2,
        "updates": [
            {"package-ecosystem": "pip", "directory": "/"},
            {"package-ecosystem": "github-actions", "directory": "/"},
        ],
    }
    assert _npm_directories(pre_fix) == []
    assert not _npm_entry_has_schedule(pre_fix, RAILWAY_NPM_DIRECTORY)


def test_dependabot_covers_railway_npm_manifest():
    """Dependabot must watch the Railway Node manifest, on a schedule."""
    config = _load_dependabot()
    assert RAILWAY_NPM_DIRECTORY in _npm_directories(config)
    assert _npm_entry_has_schedule(config, RAILWAY_NPM_DIRECTORY)


def test_dependabot_railway_entry_points_at_a_real_manifest():
    """The npm entry must track the directory holding package.json."""
    manifest = RAILWAY_DIR / "package.json"
    assert manifest.is_file(), ".railway/package.json must exist"
    declared = (json.loads(manifest.read_text(encoding="utf-8")) or {}).get(
        "dependencies", {}
    )
    assert declared, ".railway/package.json must pin at least one dependency"
    config = _load_dependabot()
    assert RAILWAY_NPM_DIRECTORY in _npm_directories(config)


def test_ruff_scope_note_is_present_and_a_rule_set_is_selected():
    """ruff.toml must enforce at least one rule family and own its narrowness."""
    text = RUFF_PATH.read_text(encoding="utf-8")
    assert 'select = ["F"]' in text or "select = ['F']" in text
    assert "Deliberate scope" in text


def test_mypy_tests_skip_is_documented_as_deliberate():
    """mypy.ini must say why tests/ sit outside the type gate."""
    text = MYPY_PATH.read_text(encoding="utf-8")
    assert "[mypy-tests.*]" in text
    assert "Deliberate" in text
