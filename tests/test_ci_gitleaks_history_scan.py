"""CI secret scan must cover the push or pull-request commit range.

``gitleaks detect --no-git`` reads the working tree and skips history, so a
secret added in one commit and removed in a later commit of the same push
never fails the job. These tests pin the bounded history scan.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
NULL_SHA = "0" * 40


def _load():
    path = ROOT / "scripts" / "ci_gitleaks_history_scan.py"
    spec = importlib.util.spec_from_file_location("ci_gitleaks_history_scan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = _load()


def _workflow():
    return yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )


def _secret_scan_steps():
    return _workflow()["jobs"]["secret_scan"]["steps"]


def _step(name: str) -> dict:
    return next(step for step in _secret_scan_steps() if step.get("name") == name)


def test_secret_scan_fetches_history_for_the_range():
    checkout = _secret_scan_steps()[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 0


def test_secret_scan_runs_the_history_scanner_on_the_event_range():
    step = _step("Scan push or pull request commits for secrets")
    assert step["run"] == "python3 scripts/ci_gitleaks_history_scan.py"
    assert "--no-git" not in step["run"]
    env = step["env"]
    assert env["EVENT_NAME"] == "${{ github.event_name }}"
    assert env["PR_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert env["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert env["PUSH_BEFORE_SHA"] == "${{ github.event.before }}"
    assert env["PUSH_AFTER_SHA"] == "${{ github.event.after }}"
    assert env["PUSH_SHA"] == "${{ github.sha }}"
    assert env["PUSH_DELETED"] == "${{ github.event.deleted }}"
    assert env["PUSH_REF"] == "${{ github.ref }}"
    assert env["DEFAULT_REF"] == "origin/${{ github.event.repository.default_branch }}"
    assert (
        env["DEFAULT_BRANCH_REF"]
        == "refs/heads/${{ github.event.repository.default_branch }}"
    )
    assert env["GITLEAKS_HISTORY_FETCH"] == "1"
    assert "github.event.commits" in env["PUSH_COMMITS_JSON"]


def test_working_tree_scan_and_canary_stay_directory_scans():
    """The tree scan and the untracked canary file are not git history."""
    tree = _step("Scan working tree for committed secrets")
    assert tree["run"].startswith("gitleaks detect --no-git ")
    canary = _step("Verify scanner still catches a known-bad credential")["run"]
    assert "gitleaks detect --no-git " in canary


def test_pull_request_scans_base_to_head():
    opts = scan.history_log_opts(
        event_name="pull_request",
        pr_base_sha=SHA_A,
        pr_head_sha=SHA_B,
    )
    assert opts == [f"-m {SHA_A}..{SHA_B}"]


def test_push_scans_previous_tip_to_pushed_commit():
    opts = scan.history_log_opts(
        event_name="push",
        push_before_sha=SHA_A,
        push_sha=SHA_B,
        before_commit_present=True,
        commits_truncated=True,
        fallback_commit_ids=[SHA_C] * 20,
        pushed_ref_is_default=True,
    )
    assert opts == [f"-m {SHA_A}..{SHA_B}"]


def test_new_branch_scans_commits_absent_from_the_default_branch():
    opts = scan.history_log_opts(
        event_name="push",
        push_before_sha=NULL_SHA,
        push_sha=SHA_B,
        before_commit_present=False,
        default_ref="origin/main",
        default_ref_present=True,
        pushed_ref_is_default=False,
    )
    assert opts == [f"-m origin/main..{SHA_B}"]


def test_missing_previous_tip_on_the_default_branch_scans_listed_commits_only():
    opts = scan.history_log_opts(
        event_name="push",
        push_before_sha=NULL_SHA,
        push_sha=SHA_B,
        before_commit_present=False,
        default_ref="origin/main",
        default_ref_present=True,
        pushed_ref_is_default=True,
        fallback_commit_ids=[SHA_A, SHA_B],
    )
    assert opts == [f"-m -n 1 {SHA_A}", f"-m -n 1 {SHA_B}"]
    assert all("--all" not in item.split() for item in opts)
    assert all(".." not in item for item in opts)


def test_unreachable_previous_tip_is_refused():
    with pytest.raises(scan.ScanRangeError, match="not in this clone"):
        scan.history_log_opts(
            event_name="push",
            push_before_sha=SHA_A,
            push_sha=SHA_B,
            before_commit_present=False,
            fallback_commit_ids=[SHA_B],
        )


def test_truncated_commit_list_is_refused_when_the_previous_tip_is_null():
    with pytest.raises(scan.ScanRangeError, match="part of the commits"):
        scan.history_log_opts(
            event_name="push",
            push_before_sha=NULL_SHA,
            push_sha=SHA_B,
            pushed_ref_is_default=True,
            fallback_commit_ids=[SHA_C] * 20,
            commits_truncated=True,
        )


def test_branch_deletion_introduces_no_commits():
    # ``github.sha`` on a delete can be the default branch, not the null SHA.
    assert (
        scan.history_log_opts(
            event_name="push",
            push_before_sha=SHA_A,
            push_sha=SHA_B,
            push_deleted=True,
            before_commit_present=True,
        )
        == []
    )
    assert (
        scan.history_log_opts(
            event_name="push",
            push_before_sha=SHA_A,
            push_sha=NULL_SHA,
        )
        == []
    )


def test_fallback_list_includes_an_omitted_tip():
    opts = scan.history_log_opts(
        event_name="push",
        push_before_sha=NULL_SHA,
        push_sha=SHA_B,
        pushed_ref_is_default=True,
        fallback_commit_ids=[SHA_A],
    )
    assert opts == [f"-m -n 1 {SHA_A}", f"-m -n 1 {SHA_B}"]


def test_resolve_push_uses_the_after_sha_when_the_previous_tip_exists():
    env = {
        "EVENT_NAME": "push",
        "PUSH_BEFORE_SHA": SHA_A,
        "PUSH_AFTER_SHA": SHA_B,
        "PUSH_SHA": SHA_C,
        "PUSH_DELETED": "false",
        "PUSH_REF": "refs/heads/main",
        "DEFAULT_BRANCH_REF": "refs/heads/main",
        "DEFAULT_REF": "origin/main",
        "PUSH_COMMITS_JSON": "null",
    }
    opts = scan.resolve_history_log_opts(env, lambda rev: rev == SHA_A)
    assert opts == [f"-m {SHA_A}..{SHA_B}"]


def test_push_with_no_range_is_refused():
    with pytest.raises(scan.ScanRangeError, match="no commits"):
        scan.history_log_opts(
            event_name="push",
            push_before_sha=NULL_SHA,
            push_sha=SHA_B,
            pushed_ref_is_default=True,
        )


def test_pull_request_without_shas_is_refused():
    with pytest.raises(scan.ScanRangeError, match="not a commit SHA"):
        scan.history_log_opts(event_name="pull_request")


def test_unsafe_default_ref_is_refused():
    with pytest.raises(scan.ScanRangeError, match="unsafe"):
        scan.history_log_opts(
            event_name="push",
            push_before_sha=NULL_SHA,
            push_sha=SHA_B,
            default_ref="--all",
            default_ref_present=True,
            pushed_ref_is_default=False,
        )


def test_history_command_is_a_git_scan():
    command = scan.gitleaks_command(f"-m {SHA_A}..{SHA_B}")
    assert "--no-git" not in command
    assert f"--log-opts=-m {SHA_A}..{SHA_B}" in command
    with pytest.raises(scan.ScanRangeError, match="bounded"):
        scan.gitleaks_command("--all")
    with pytest.raises(scan.ScanRangeError, match="bounded"):
        scan.gitleaks_command("--no-git")


def test_scope_note_documents_the_bounded_history_scan():
    text = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    assert "push or pull request" in text
    assert "WORKING TREE for speed" not in text


def _git(cwd: Path, *args: str) -> str:
    argv = ["git", *args]
    if args and args[0] == "commit":
        argv = ["git", "-c", "commit.gpgsign=false", *args]
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "scan-test",
            "GIT_AUTHOR_EMAIL": "scan-test@example.com",
            "GIT_COMMITTER_NAME": "scan-test",
            "GIT_COMMITTER_EMAIL": "scan-test@example.com",
        }
    )
    completed = subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def test_real_clone_checks_both_ends_of_the_push_range(tmp_path: Path):
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "note.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "note.txt")
    _git(tmp_path, "commit", "-m", "first")
    first = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "note.txt").write_text("two\n", encoding="utf-8")
    _git(tmp_path, "add", "note.txt")
    _git(tmp_path, "commit", "-m", "second")
    second = _git(tmp_path, "rev-parse", "HEAD")

    def exists(rev: str) -> bool:
        return scan.commit_exists(rev, cwd=tmp_path)

    assert exists(first)
    assert exists(second)
    assert not exists(NULL_SHA)
    present = scan.history_log_opts(
        event_name="push",
        push_before_sha=first,
        push_sha=second,
        before_commit_present=True,
    )
    assert present == [f"-m {first}..{second}"]
    scan.assert_revisions_exist(present[0], exists)

    missing = scan.history_log_opts(
        event_name="push",
        push_before_sha=first,
        push_sha=SHA_B,
        before_commit_present=True,
    )
    with pytest.raises(scan.ScanRangeError, match="not in this clone"):
        scan.assert_revisions_exist(missing[0], exists)


@pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks is not installed"
)
def test_history_scan_catches_a_secret_the_working_tree_scan_misses(tmp_path: Path):
    """A commit that adds a credential and a later commit that removes it.

    ``--no-git`` only sees the tip, which is clean. The bounded history
    scan sees the commit that introduced the credential.
    """
    _git(tmp_path, "init", "-b", "main")
    shutil.copyfile(ROOT / ".gitleaks.toml", tmp_path / ".gitleaks.toml")
    (tmp_path / "README").write_text("clean\n", encoding="utf-8")
    _git(tmp_path, "add", "README")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    # Split the assignment so this test source is not itself a finding if
    # the tests/ allowlist is ever narrowed.
    secret = "API_KEY = " + '"canary-lowentropy-credential-must-be-flagged"\n'
    leaked = tmp_path / "leaked.py"
    leaked.write_text(secret, encoding="utf-8")
    _git(tmp_path, "add", "leaked.py")
    _git(tmp_path, "commit", "-m", "introduce credential")
    leaked.write_text("value = os.environ['API_KEY']\n", encoding="utf-8")
    _git(tmp_path, "add", "leaked.py")
    _git(tmp_path, "commit", "-m", "remove credential")
    tip = _git(tmp_path, "rev-parse", "HEAD")

    tree = subprocess.run(
        [
            "gitleaks",
            "detect",
            "--no-git",
            "--source",
            ".",
            "--config",
            ".gitleaks.toml",
            "--redact",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tree.returncode == 0, tree.stderr

    history = subprocess.run(
        scan.gitleaks_command(f"-m {base}..{tip}"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert history.returncode == 1, history.stdout + history.stderr

    (tmp_path / "README").write_text("still clean\n", encoding="utf-8")
    _git(tmp_path, "add", "README")
    _git(tmp_path, "commit", "-m", "after the secret was removed")
    later = _git(tmp_path, "rev-parse", "HEAD")
    ancestor = subprocess.run(
        scan.gitleaks_command(f"-m {tip}..{later}"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestor.returncode == 0, ancestor.stdout + ancestor.stderr
