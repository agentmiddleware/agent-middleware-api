"""CI secret-scan commit range (scripts/secret_scan_range.sh).

The range scan is the only check that catches a secret added in one commit
and deleted in a later one of the same push. These tests build real git
histories and assert the selected range still contains the commit that added
the secret, especially when the push base is missing (branch creation or a
force push whose old tip is gone). In that case the old fallback,
origin/main..HEAD, was always empty on a push to main.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "secret_scan_range.sh"
ZERO_SHA = "0" * 40
# Assembled at runtime so this file holds no credential-shaped literal.
CANARY_LINE = 'API_KEY = "%s"\n' % ("canary-lowentropy-" + "credential-in-history")


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    """main: base -> add_secret -> delete_secret -> head."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "ci")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("base\n")
    base = _commit(repo, "base")
    (repo / "leak.py").write_text(CANARY_LINE)
    add_secret = _commit(repo, "add secret")
    (repo / "leak.py").unlink()
    _commit(repo, "delete secret")
    (repo / "README.md").write_text("head\n")
    head = _commit(repo, "head")
    return {"repo": repo, "base": base, "add_secret": add_secret, "head": head}


def _range(repo, verified_base=None, **env):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    full_env.update(env)
    if verified_base:
        full_env["SECRET_SCAN_VERIFIED_BASE"] = verified_base
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env=full_env,
        capture_output=True,
        text=True,
    )


def _commits_in(repo, rev_range):
    out = _git(repo, "rev-list", rev_range)
    return set(out.split()) if out else set()


def _assert_covers_secret(history, result):
    assert result.returncode == 0, result.stderr
    rev_range = result.stdout.strip()
    commits = _commits_in(history["repo"], rev_range)
    assert commits, f"range {rev_range!r} is empty; nothing would be scanned"
    assert history["add_secret"] in commits, (
        f"range {rev_range!r} skips the commit that added the secret"
    )


def test_normal_push_scans_before_to_head(history):
    result = _range(
        history["repo"],
        EVENT_NAME="push",
        PUSH_BEFORE_SHA=history["base"],
        PUSH_SHA=history["head"],
    )
    assert result.stdout.strip() == f"{history['base']}..{history['head']}"
    _assert_covers_secret(history, result)


def test_pull_request_scans_base_to_head(history):
    result = _range(
        history["repo"],
        EVENT_NAME="pull_request",
        PR_BASE_SHA=history["base"],
        PR_HEAD_SHA=history["head"],
    )
    _assert_covers_secret(history, result)


@pytest.mark.parametrize(
    "before",
    [
        pytest.param(ZERO_SHA, id="branch-creation"),
        pytest.param("", id="before-empty"),
        # A force push: the old tip is not in the clone and cannot be fetched
        # (this repo has no origin).
        pytest.param("deadbeef" * 5, id="force-push-old-tip-missing"),
    ],
)
def test_missing_base_falls_back_to_verified_base(history, before):
    result = _range(
        history["repo"],
        verified_base=history["base"],
        EVENT_NAME="push",
        PUSH_BEFORE_SHA=before,
        PUSH_SHA=history["head"],
    )
    assert result.stdout.strip() == f"{history['base']}..{history['head']}"
    _assert_covers_secret(history, result)


def test_fallback_not_empty_when_origin_main_is_the_pushed_head(history):
    """Regression: on a push to main, origin/main == PUSH_SHA, so the old
    origin/main..PUSH_SHA fallback scanned zero commits."""
    repo = history["repo"]
    _git(repo, "update-ref", "refs/remotes/origin/main", history["head"])
    assert _commits_in(repo, f"origin/main..{history['head']}") == set()
    result = _range(
        repo,
        verified_base=history["base"],
        EVENT_NAME="push",
        PUSH_BEFORE_SHA=ZERO_SHA,
        PUSH_SHA=history["head"],
    )
    _assert_covers_secret(history, result)


def test_fallback_fails_closed_when_history_rewritten_below_base(history):
    """If the verified base is no longer an ancestor, the range would skip the
    rewritten commits. The script must error, not scan a partial range."""
    repo = history["repo"]
    _git(repo, "checkout", "-q", "--orphan", "rewritten")
    (repo / "leak.py").write_text(CANARY_LINE)
    _commit(repo, "rewritten root with secret")
    rewritten_head = _commit(repo, "rewritten head")
    result = _range(
        repo,
        verified_base=history["base"],
        EVENT_NAME="push",
        PUSH_BEFORE_SHA="deadbeef" * 5,
        PUSH_SHA=rewritten_head,
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "not an ancestor" in result.stderr


def test_pinned_verified_base_is_on_this_history():
    """The pinned fallback base must be an ancestor of the checkout, or every
    fallback run on main would fail closed."""
    text = SCRIPT.read_text(encoding="utf-8")
    pinned = text.split("SECRET_SCAN_VERIFIED_BASE:-", 1)[1].split("}", 1)[0]
    assert len(pinned) == 40
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{pinned}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if present.returncode != 0:
        pytest.skip("shallow checkout: pinned base not present")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", pinned, "HEAD"],
        cwd=REPO_ROOT,
        check=True,
    )


def test_workflow_scans_the_script_range():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    step = next(
        s
        for s in workflow["jobs"]["secret_scan"]["steps"]
        if s.get("name") == "Scan commit range for committed secrets"
    )
    run = step["run"]
    assert "scripts/secret_scan_range.sh" in run
    assert '--log-opts="${range}"' in run
    # The pinned base override is for tests only.
    assert "SECRET_SCAN_VERIFIED_BASE" not in step.get("env", {})


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_gitleaks_flags_deleted_secret_in_fallback_range(history):
    result = _range(
        history["repo"],
        verified_base=history["base"],
        EVENT_NAME="push",
        PUSH_BEFORE_SHA=ZERO_SHA,
        PUSH_SHA=history["head"],
    )
    assert result.returncode == 0, result.stderr
    scan = subprocess.run(
        [
            "gitleaks",
            "detect",
            "--source",
            str(history["repo"]),
            "--config",
            str(REPO_ROOT / ".gitleaks.toml"),
            "--redact",
            f"--log-opts={result.stdout.strip()}",
        ],
        capture_output=True,
        text=True,
    )
    assert scan.returncode != 0, "gitleaks missed a secret deleted later in the push"
