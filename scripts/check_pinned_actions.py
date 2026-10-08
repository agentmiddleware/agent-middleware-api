"""Fail-closed check that every GitHub Actions step pins a full commit SHA.

Rule: every ``uses:`` value under ``.github/workflows`` must be either

- ``<owner>/<repo>[@<path>]@<40-hex-sha>`` with a trailing ``# vN`` version
  comment (so reviewers can see which release the SHA belongs to), or
- a local path starting with ``./`` (a checked-in composite action, so no
  remote code is fetched at run time).

Anything else (a tag such as ``@v4``, a branch such as ``@main``, ``@latest``,
a short SHA, or a pinned SHA with no version comment) is a violation and the
script exits 1 listing each one. There is no network access and no third-party
dependency, so the check itself cannot be broken by a supply-chain event.

Used by ``.github/workflows/supply-chain.yml`` and by
``tests/test_pinned_actions.py``.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

USES_RE = re.compile(
    r"""^[ \t]*-[ \t]*uses:[ \t]*
        (?P<quote>["']?)(?P<target>[^"'#\s]+)(?P=quote)
        [ \t]*(?:\#(?P<comment>.*))?$""",
    re.VERBOSE,
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT_RE = re.compile(r"v\d+(\.\d+)*")


def check_text(text, *, source):
    """Return a list of violation strings for one workflow file's text."""
    violations = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = USES_RE.match(line)
        if not match:
            continue
        target = match.group("target")
        comment = (match.group("comment") or "").strip()
        if target.startswith("./") or target.startswith("../"):
            continue
        if "@" not in target:
            violations.append(
                "%s:%d: %s has no ref at all, pin a full commit SHA"
                % (source, lineno, target)
            )
            continue
        ref = target.rsplit("@", 1)[1]
        if not SHA_RE.match(ref):
            violations.append(
                "%s:%d: %s is not a full 40-hex commit SHA, pin the action"
                % (source, lineno, target)
            )
            continue
        if not VERSION_COMMENT_RE.search(comment):
            violations.append(
                "%s:%d: %s pins a SHA but has no version comment, add # vN"
                % (source, lineno, target)
            )
    return violations


def check_file(path):
    """Return violations for a single workflow file."""
    return check_text(Path(path).read_text(encoding="utf-8"), source=str(path))


def check_tree(workflows_dir):
    """Return violations for every .yml/.yaml file in a directory."""
    violations = []
    for path in sorted(Path(workflows_dir).glob("*.y*ml")):
        violations.extend(check_file(path))
    return violations


def main(argv):
    workflows_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_WORKFLOWS_DIR
    if not workflows_dir.is_dir():
        print("error: not a directory: %s" % workflows_dir)
        return 2
    violations = check_tree(workflows_dir)
    for violation in violations:
        print(violation)
    if violations:
        print("%d unpinned action ref(s) found" % len(violations))
        return 1
    print("all action refs pinned to full commit SHAs with version comments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
