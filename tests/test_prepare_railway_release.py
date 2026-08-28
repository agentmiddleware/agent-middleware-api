"""Tests for immutable Railway release-context preparation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import prepare_railway_release as release


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def detached_release_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "release-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Release Test")
    (repo / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("", encoding="utf-8")
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "docker_entrypoint.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("release source\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "release source")
    commit_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", commit_sha)
    return repo, commit_sha


def test_prepares_archive_context_with_exact_immutable_stamp(
    detached_release_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, commit_sha = detached_release_repo

    context = release.prepare_release_context(
        ref=commit_sha,
        repo_root=repo,
        staging_parent=tmp_path,
    )

    assert context.parent == tmp_path
    assert (context / "tracked.txt").read_text(encoding="utf-8") == "release source\n"
    assert (context / ".build_commit_sha").read_text(encoding="utf-8") == f"{commit_sha}\n"
    assert (context / ".build_commit_sha").stat().st_mode & 0o777 == 0o444
    assert not (context / ".git").exists()


def test_prepares_archive_context_in_the_system_temp_directory(
    detached_release_repo: tuple[Path, str],
) -> None:
    repo, commit_sha = detached_release_repo
    context = release.prepare_release_context(ref=commit_sha, repo_root=repo)

    try:
        assert (context / ".build_commit_sha").read_text(encoding="utf-8") == (
            f"{commit_sha}\n"
        )
    finally:
        shutil.rmtree(context)


def test_rejects_branch_checkout(
    detached_release_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, commit_sha = detached_release_repo
    _git(repo, "checkout", "main")

    with pytest.raises(release.ReleaseContextError, match="detached checkout"):
        release.prepare_release_context(
            ref=commit_sha,
            repo_root=repo,
            staging_parent=tmp_path,
        )


def test_rejects_dirty_checkout(
    detached_release_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, commit_sha = detached_release_repo
    (repo / "untracked.txt").write_text("not release source\n", encoding="utf-8")

    with pytest.raises(release.ReleaseContextError, match="clean checkout"):
        release.prepare_release_context(
            ref=commit_sha,
            repo_root=repo,
            staging_parent=tmp_path,
        )


def test_rejects_archive_with_preexisting_stamp(tmp_path: Path) -> None:
    repo = tmp_path / "release-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Release Test")
    (repo / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("", encoding="utf-8")
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "docker_entrypoint.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / ".build_commit_sha").write_text("a" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "bad release source")
    commit_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", commit_sha)

    with pytest.raises(release.ReleaseContextError, match="must not already contain"):
        release.prepare_release_context(
            ref=commit_sha,
            repo_root=repo,
            staging_parent=tmp_path,
        )
