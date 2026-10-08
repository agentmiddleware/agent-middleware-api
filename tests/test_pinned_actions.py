"""Tests for the pinned-actions supply-chain gate.

``scripts/check_pinned_actions.py`` plus ``.github/workflows/supply-chain.yml``
are the one shared mechanism that keeps every GitHub Actions step pinned to a
full commit SHA with a version comment. Before this change no script, test, or
workflow enforced anything, so a tag ref such as ``actions/checkout@v4`` would
have merged with CI green.
"""

import importlib.util
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER_PATH = REPO_ROOT / "scripts" / "check_pinned_actions.py"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
GATE_PATH = WORKFLOWS_DIR / "supply-chain.yml"

PINNED = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7"
SHORT_SHA = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b # v7"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_pinned_actions", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(text):
    return "- uses: %s\n" % text


def test_pinned_sha_with_version_comment_passes():
    checker = _load_checker()
    assert checker.check_text(_doc(PINNED), source="t.yml") == []


def test_local_action_path_passes():
    checker = _load_checker()
    assert checker.check_text("- uses: ./.github/actions/setup\n", source="t.yml") == []


def test_tag_ref_fails():
    checker = _load_checker()
    violations = checker.check_text(_doc("actions/checkout@v4"), source="t.yml")
    assert len(violations) == 1
    assert "t.yml:1" in violations[0]


def test_branch_ref_fails():
    checker = _load_checker()
    violations = checker.check_text(_doc("actions/checkout@main"), source="t.yml")
    assert len(violations) == 1


def test_latest_ref_fails():
    checker = _load_checker()
    target = "docker/build-push-action@latest # v7"
    assert checker.check_text(_doc(target), source="t.yml") != []


def test_short_sha_fails():
    checker = _load_checker()
    assert checker.check_text(_doc(SHORT_SHA), source="t.yml") != []


def test_missing_version_comment_fails():
    checker = _load_checker()
    bare = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    violations = checker.check_text(_doc(bare), source="t.yml")
    assert len(violations) == 1
    assert "version comment" in violations[0]


def test_missing_ref_fails():
    checker = _load_checker()
    assert checker.check_text("- uses: actions/checkout\n", source="t.yml") != []


def test_real_workflows_tree_passes():
    checker = _load_checker()
    assert checker.check_tree(WORKFLOWS_DIR) == []


def test_fixture_tree_with_unpinned_ref_fails(tmp_path):
    checker = _load_checker()
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "jobs:\n  x:\n    steps:\n      %s" % _doc("actions/checkout@v4"),
        encoding="utf-8",
    )
    good = tmp_path / "good.yml"
    good.write_text(
        "jobs:\n  x:\n    steps:\n      %s" % _doc(PINNED), encoding="utf-8"
    )
    violations = checker.check_tree(tmp_path)
    assert len(violations) == 1
    assert "bad.yml" in violations[0]


def test_cli_exit_codes(tmp_path, capsys):
    checker = _load_checker()
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.yml").write_text("steps:\n  %s" % _doc(PINNED), encoding="utf-8")
    assert checker.main(["check", str(clean)]) == 0
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "a.yml").write_text(
        "steps:\n  %s" % _doc("actions/checkout@v4"), encoding="utf-8"
    )
    assert checker.main(["check", str(dirty)]) == 1
    assert "unpinned" in capsys.readouterr().out


def test_gate_workflow_runs_checker_on_pull_request():
    gate = yaml.safe_load(GATE_PATH.read_text(encoding="utf-8"))
    # YAML 1.1 parses an unquoted `on:` key as boolean True.
    triggers = gate.get("on", gate.get(True))
    assert "pull_request" in triggers
    steps = gate["jobs"]["pinned-actions"]["steps"]
    assert any(
        "check_pinned_actions" in str(step.get("run", ""))
        for step in steps
        if isinstance(step, dict)
    )


def test_gate_workflow_own_refs_pass_checker():
    checker = _load_checker()
    assert checker.check_file(GATE_PATH) == []
