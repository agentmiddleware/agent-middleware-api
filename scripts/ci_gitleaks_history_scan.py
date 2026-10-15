#!/usr/bin/env python3
"""Scan commits introduced by a push or pull request for secrets.

``gitleaks detect --no-git`` reads the working tree only. A credential
committed and then removed before the tip never appears there. This
command scans that history, bounded to the push or pull-request range.

An unbounded scan is refused. The rotated 2026-08-06 key is still an
ancestor of main (see ``docs/api-key-rotation.md`` and the scope note in
``.gitleaks.toml``), so walking every ancestor would fail every run.

Gitleaks 8.21.2 passes ``--log-opts`` to ``git log -p -U0`` and, when the
flag is omitted, adds ``--all``. A range that does not resolve can also
be reported as a clean scan (gitleaks issue 1450). This script names the
range itself and checks that both ends exist before invoking gitleaks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

NULL_SHA = "0" * 40
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
# GitHub's push payload lists at most this many commits. A list of that
# length may be truncated, so it is not a complete range.
_PUSH_COMMIT_CAP = 20
ROOT = Path(__file__).resolve().parent.parent

CommitExists = Callable[[str], bool]


class ScanRangeError(Exception):
    """The event did not name a bounded commit range that this clone can scan."""


def _sha(value: str | None, label: str) -> str:
    text = (value or "").strip().lower()
    if not _SHA.fullmatch(text):
        raise ScanRangeError(f"{label} is not a commit SHA")
    return text


def _safe_ref(value: str) -> str:
    if (
        not _REF.fullmatch(value)
        or ".." in value
        or "@{" in value
        or value.endswith("/")
    ):
        raise ScanRangeError("refusing an unsafe git revision")
    return value


def commit_ids_from_event(payload: str | None) -> list[str]:
    """Return commit ids from a GitHub push ``commits`` JSON array."""
    text = (payload or "").strip()
    if text in {"", "null"}:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScanRangeError("push commits payload is not JSON") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ScanRangeError("push commits payload is not a list")
    ids: list[str] = []
    for item in data:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        else:
            raise ScanRangeError("push commits payload has an entry without an id")
    return ids


def history_log_opts(
    *,
    event_name: str,
    pr_base_sha: str | None = None,
    pr_head_sha: str | None = None,
    push_before_sha: str | None = None,
    push_sha: str | None = None,
    push_deleted: bool = False,
    before_commit_present: bool = False,
    default_ref: str | None = None,
    default_ref_present: bool = False,
    pushed_ref_is_default: bool = False,
    fallback_commit_ids: list[str] | None = None,
    commits_truncated: bool = False,
) -> list[str]:
    """Return ``git log`` options for the commits this event introduced.

    Each string is one gitleaks ``--log-opts`` value. ``-m`` includes the
    patch of a merge commit, which ``git log -p`` otherwise omits. ``-n 1``
    is used only when the previous tip does not exist, so a bare SHA cannot
    walk ancestors that still contain the rotated key.
    """
    if event_name == "pull_request":
        base = _sha(pr_base_sha, "pull request base")
        head = _sha(pr_head_sha, "pull request head")
        return [f"-m {base}..{head}"]

    if event_name != "push":
        raise ScanRangeError(f"unsupported event {event_name}")

    # Deleting a ref introduces no commit. ``github.sha`` on that event can
    # be the default branch, so scanning it would read unrelated history.
    if push_deleted or (push_sha or "").strip().lower() == NULL_SHA:
        return []

    head = _sha(push_sha, "pushed commit")
    before = (push_before_sha or "").strip().lower()
    if before and before != NULL_SHA:
        before = _sha(before, "previous tip")
        if not before_commit_present:
            raise ScanRangeError(
                "previous tip is not in this clone, so the push range cannot be scanned"
            )
        return [f"-m {before}..{head}"]

    if default_ref and default_ref_present and not pushed_ref_is_default:
        return [f"-m {_safe_ref(default_ref)}..{head}"]

    if commits_truncated:
        raise ScanRangeError(
            "previous tip is unavailable and the push event listed only "
            "part of the commits"
        )
    ids = [
        _sha(raw, "pushed commit id")
        for raw in (fallback_commit_ids or [])
        if raw and raw.strip().lower() != NULL_SHA
    ]
    if not ids:
        raise ScanRangeError(
            "previous tip is unavailable and the push event listed no commits"
        )
    if head not in ids:
        ids.append(head)
    return [f"-m -n 1 {commit_id}" for commit_id in ids]


def resolve_history_log_opts(
    env: Mapping[str, str], commit_exists: CommitExists
) -> list[str]:
    """Build the range from the CI environment."""
    before = (env.get("PUSH_BEFORE_SHA") or "").strip().lower()
    before_present = bool(before) and before != NULL_SHA and commit_exists(before)
    default_ref = (env.get("DEFAULT_REF") or "").strip()
    commits = commit_ids_from_event(env.get("PUSH_COMMITS_JSON"))
    event_name = (env.get("EVENT_NAME") or "").strip()
    after = (env.get("PUSH_AFTER_SHA") or "").strip()
    # ``after`` is the ref's new tip. On a pull request it is empty, and
    # ``github.sha`` is the merge commit, which is not the range head.
    push_sha = after if event_name == "push" and after else env.get("PUSH_SHA")
    return history_log_opts(
        event_name=event_name,
        pr_base_sha=env.get("PR_BASE_SHA"),
        pr_head_sha=env.get("PR_HEAD_SHA"),
        push_before_sha=before,
        push_sha=push_sha,
        push_deleted=(env.get("PUSH_DELETED") or "").strip().lower() == "true",
        before_commit_present=before_present,
        default_ref=default_ref or None,
        default_ref_present=bool(default_ref) and commit_exists(default_ref),
        pushed_ref_is_default=(env.get("PUSH_REF") or "")
        == (env.get("DEFAULT_BRANCH_REF") or "refs/heads/main"),
        fallback_commit_ids=commits,
        commits_truncated=len(commits) >= _PUSH_COMMIT_CAP,
    )


def revisions_in(log_opts: str) -> list[str]:
    """Return the revisions inside one log-opts string, dropping diff flags."""
    parts = log_opts.split()
    revisions: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "-m":
            index += 1
            continue
        if part == "-n":
            index += 2
            continue
        if part.startswith("-"):
            raise ScanRangeError(f"unexpected git log flag: {part}")
        revisions.append(part)
        index += 1
    if not revisions:
        raise ScanRangeError("history scan named no revision")
    return revisions


def gitleaks_command(log_opts: str) -> list[str]:
    """Argv for one bounded history scan. Never a directory scan."""
    tokens = log_opts.split()
    if not tokens or "--all" in tokens or "--no-git" in tokens:
        raise ScanRangeError("history scan must stay a bounded git range")
    revisions_in(log_opts)
    return [
        "gitleaks",
        "detect",
        "--source",
        ".",
        "--config",
        ".gitleaks.toml",
        "--redact",
        "--verbose",
        f"--log-opts={log_opts}",
    ]


def commit_exists(rev: str, *, cwd: Path = ROOT) -> bool:
    """True when ``rev`` names a commit in ``cwd``. The null SHA does not."""
    text = (rev or "").strip()
    if not text or text.lower() == NULL_SHA:
        return False
    # A two-dot range is not a single object. Callers check each end.
    if ".." in text or text.startswith("-"):
        return False
    probe = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{text}^{{commit}}",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def assert_revisions_exist(log_opts: str, commit_exists_fn: CommitExists) -> None:
    """Fail before gitleaks if either end of the range is missing.

    Gitleaks has reported a clean result when ``git log`` itself failed.
    Checking the endpoints here keeps a missing range from looking like
    a scan with no findings.
    """
    for revision in revisions_in(log_opts):
        if revision.count("..") == 1:
            left, right = revision.split("..", 1)
            ends = (left, right)
        elif ".." in revision:
            raise ScanRangeError("history scan range is malformed")
        else:
            ends = (revision,)
        for end in ends:
            if not end or not commit_exists_fn(end):
                raise ScanRangeError(
                    f"revision is not in this clone: {end or revision}"
                )


def _fetch(rev: str) -> None:
    """Fetch one missing SHA, or ``main`` when the default ref is absent."""
    if _SHA.fullmatch(rev):
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", rev],
            cwd=ROOT,
            check=False,
        )
        return
    if rev == "origin/main":
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", "main"],
            cwd=ROOT,
            check=False,
        )


def _ensure_objects(env: Mapping[str, str]) -> None:
    if env.get("GITLEAKS_HISTORY_FETCH") != "1":
        return
    event = (env.get("EVENT_NAME") or "").strip()
    wanted: list[str] = []
    if event == "pull_request":
        wanted.extend(
            [
                (env.get("PR_BASE_SHA") or "").strip().lower(),
                (env.get("PR_HEAD_SHA") or "").strip().lower(),
            ]
        )
    elif event == "push":
        before = (env.get("PUSH_BEFORE_SHA") or "").strip().lower()
        if before and before != NULL_SHA:
            wanted.append(before)
        default_ref = (env.get("DEFAULT_REF") or "").strip()
        if default_ref:
            wanted.append(default_ref)
    for rev in wanted:
        if rev and not commit_exists(rev):
            _fetch(rev)


def main(env: Mapping[str, str] | None = None) -> int:
    """Scan the event's commit range. Returns the gitleaks status."""
    values = os.environ if env is None else env
    _ensure_objects(values)
    try:
        planned: list[tuple[str, list[str]]] = []
        for log_opts in resolve_history_log_opts(values, commit_exists):
            assert_revisions_exist(log_opts, commit_exists)
            planned.append((log_opts, gitleaks_command(log_opts)))
    except ScanRangeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if not planned:
        print("No commits introduced; history scan skipped.")
        return 0
    for log_opts, command in planned:
        print(f"Scanning git history with log options: {log_opts}", flush=True)
        try:
            completed = subprocess.run(command, cwd=ROOT, check=False)
        except FileNotFoundError:
            print("::error::gitleaks is not installed", file=sys.stderr)
            return 127
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
