#!/usr/bin/env python3
"""Create an immutable, exact-SHA Railway upload context.

The release context is a fresh Git archive from the detached, clean checkout
that owns the release. It carries a generated ``.build_commit_sha`` file, so
Railway receives the source and its provenance stamp in one upload instead of
reading a mutable service variable.
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_STAMP_NAME = ".build_commit_sha"
_REQUIRED_FILES = ("Dockerfile", "requirements.txt", "scripts/docker_entrypoint.sh")


class ReleaseContextError(RuntimeError):
    """Raised when a release context cannot safely be prepared."""


def _git_text(arguments: list[str], *, repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ReleaseContextError(f"could not run git: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise ReleaseContextError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _git_archive(commit_sha: str, *, repo_root: Path) -> bytes:
    try:
        result = subprocess.run(
            ["git", "archive", "--format=tar", commit_sha],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise ReleaseContextError(f"could not run git archive: {error}") from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseContextError(f"git archive failed: {detail or 'unknown git error'}")
    return result.stdout


def _require_detached_checkout(*, repo_root: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ReleaseContextError(f"could not inspect HEAD state: {error}") from error
    if result.returncode == 0:
        raise ReleaseContextError("release preparation requires a detached checkout")
    if result.returncode != 1:
        detail = result.stderr.strip() or "unknown git error"
        raise ReleaseContextError(f"could not inspect HEAD state: {detail}")


def _require_clean_checkout(*, repo_root: Path) -> None:
    status = _git_text(
        ["status", "--porcelain=v1", "--untracked-files=all"], repo_root=repo_root
    )
    if status.strip():
        raise ReleaseContextError("release preparation requires a clean checkout")


def _extract_archive(archive: bytes, destination: Path) -> None:
    destination = destination.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle:
                relative_path = Path(member.name)
                resolved_path = (destination / relative_path).resolve()
                if (
                    relative_path.is_absolute()
                    or ".." in relative_path.parts
                    or (
                        resolved_path != destination
                        and destination not in resolved_path.parents
                    )
                ):
                    raise ReleaseContextError(
                        f"git archive contains an unsafe path: {member.name}"
                    )
                if not (member.isfile() or member.isdir()):
                    raise ReleaseContextError(
                        f"git archive contains unsupported entry: {member.name}"
                    )
                if member.isdir():
                    resolved_path.mkdir(parents=True, exist_ok=True)
                    resolved_path.chmod(member.mode & 0o777)
                    continue

                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ReleaseContextError(
                        f"git archive could not read file: {member.name}"
                    )
                with source, resolved_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                resolved_path.chmod(member.mode & 0o777)
    except (OSError, tarfile.TarError) as error:
        raise ReleaseContextError(f"could not extract release archive: {error}") from error


def prepare_release_context(
    *,
    ref: str = "HEAD",
    repo_root: Path = REPO_ROOT,
    staging_parent: Path | None = None,
) -> Path:
    """Archive the exact detached SHA, add its stamp, and return the new context."""
    repo_root = repo_root.resolve()
    _require_clean_checkout(repo_root=repo_root)
    _require_detached_checkout(repo_root=repo_root)

    commit_sha = _git_text(["rev-parse", "--verify", f"{ref}^{{commit}}"], repo_root=repo_root)
    commit_sha = commit_sha.strip().lower()
    if _SHA_RE.fullmatch(commit_sha) is None:
        raise ReleaseContextError("release ref did not resolve to a full 40-character SHA")
    head_sha = _git_text(["rev-parse", "HEAD"], repo_root=repo_root).strip().lower()
    if head_sha != commit_sha:
        raise ReleaseContextError("release ref must match the detached checkout HEAD")

    submodules = _git_text(["submodule", "status", "--recursive"], repo_root=repo_root)
    if submodules.strip():
        raise ReleaseContextError("release archive cannot include submodules")

    parent = staging_parent.resolve() if staging_parent is not None else None
    try:
        context = Path(
            tempfile.mkdtemp(prefix=f"railway-release-{commit_sha[:12]}-", dir=parent)
        )
    except OSError as error:
        raise ReleaseContextError(f"could not create release context: {error}") from error

    try:
        _extract_archive(_git_archive(commit_sha, repo_root=repo_root), context)
        if (context / ".git").exists() or (context / ".git").is_symlink():
            raise ReleaseContextError("release archive unexpectedly contains .git")
        missing = [name for name in _REQUIRED_FILES if not (context / name).is_file()]
        if missing:
            raise ReleaseContextError(
                "release archive is missing required files: " + ", ".join(missing)
            )

        stamp = context / _STAMP_NAME
        if stamp.exists() or stamp.is_symlink():
            raise ReleaseContextError(f"release archive must not already contain {_STAMP_NAME}")
        stamp.write_text(f"{commit_sha}\n", encoding="utf-8")
        stamp.chmod(0o444)
        if stamp.read_text(encoding="utf-8") != f"{commit_sha}\n":
            raise ReleaseContextError("release context stamp did not round-trip")
    except (OSError, ReleaseContextError):
        shutil.rmtree(context, ignore_errors=True)
        raise

    return context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        default="HEAD",
        help="Exact Git ref to archive; it must match the detached checkout HEAD.",
    )
    args = parser.parse_args(argv)

    try:
        context = prepare_release_context(ref=args.ref)
    except ReleaseContextError as error:
        print(f"release context blocked: {error}", file=sys.stderr)
        return 2
    print(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
