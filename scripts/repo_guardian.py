#!/usr/bin/env python3.12
"""Repo guardian for agent-middleware-api.

Consolidates four recurring checks into one loop tick so the trust plane
cannot silently regress while work is in progress:

  1. Trust-plane guardian  - core-quality-gate (ruff+mypy core slice) + prove-trust-plane
  2. Readiness gap tracker  - diff build_trust_readiness_report() against last snapshot
  3. Test + lint sweep      - full `pytest -p no:randomly` (heavy; runs with --full or on change)
  4. CI / PR watcher        - `gh` run/PR check status for the current branch

Snapshots live in .git/repo_guardian/ (never committed). Exit code is the
number of FAILED checks, so the loop can react to non-zero.

Usage:
  python3.12 scripts/repo_guardian.py            # quick tiers (1,2,4) + sweep only if code changed
  python3.12 scripts/repo_guardian.py --full     # force the heavy test sweep too
  python3.12 scripts/repo_guardian.py --no-sweep  # skip the heavy sweep entirely
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATE_DIR = ROOT / ".git" / "repo_guardian"
READINESS_SNAP = STATE_DIR / "readiness.json"
SWEEP_FINGERPRINT = STATE_DIR / "sweep_fingerprint.txt"
FINDINGS_LOG = STATE_DIR / "findings.log"
LAST_SIG = STATE_DIR / "last_failure_sig.txt"


def python_bin() -> str:
    for cand in ("python3.12", "python3", "python"):
        if shutil.which(cand):
            return cand
    return sys.executable


PY = python_bin()


def run(cmd: list[str], timeout: int = 900) -> tuple[bool, float, str]:
    """Run a command; return (ok, seconds, tail-of-output)."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - start, f"TIMEOUT after {timeout}s"
    out = (proc.stdout + proc.stderr).strip().splitlines()
    tail = "\n".join(out[-12:])
    return proc.returncode == 0, time.monotonic() - start, tail


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


# --- Tier 2: readiness gap tracker -----------------------------------------


def readiness_snapshot() -> dict:
    from app.trust.readiness import build_trust_readiness_report

    r = build_trust_readiness_report()
    return {
        "verdict": r.verdict,
        "total": r.total_items,
        "critical_gaps": sorted(r.critical_gaps),
        "items": {i.id: i.status for i in r.items},
    }


def diff_readiness(prev: dict | None, cur: dict) -> tuple[bool, list[str]]:
    """Return (regressed, human-readable change lines)."""
    rank = {
        "verified": 3,
        "partially_verified": 2,
        "demo_only": 1,
        "not_verified": 0,
    }
    lines: list[str] = []
    regressed = False
    if prev is None:
        lines.append(
            f"baseline: verdict={cur['verdict']} items={cur['total']} "
            f"critical_gaps={cur['critical_gaps'] or 'none'}"
        )
        return False, lines

    if prev["verdict"] != cur["verdict"]:
        lines.append(f"verdict: {prev['verdict']} -> {cur['verdict']}")
    for item_id, status in cur["items"].items():
        old = prev["items"].get(item_id)
        if old is None:
            lines.append(f"+ new item {item_id}: {status}")
        elif old != status:
            arrow = (
                "improved" if rank.get(status, 0) > rank.get(old, 0) else "REGRESSED"
            )
            if arrow == "REGRESSED":
                regressed = True
            lines.append(f"  {item_id}: {old} -> {status} ({arrow})")
    for item_id in prev["items"].keys() - cur["items"].keys():
        lines.append(f"- removed item {item_id}")
    new_gaps = set(cur["critical_gaps"]) - set(prev["critical_gaps"])
    if new_gaps:
        regressed = True
        lines.append(f"  NEW critical gaps: {sorted(new_gaps)}")
    closed_gaps = set(prev["critical_gaps"]) - set(cur["critical_gaps"])
    if closed_gaps:
        lines.append(f"  closed critical gaps: {sorted(closed_gaps)}")
    if not lines:
        lines.append("no change since last snapshot")
    return regressed, lines


# --- Tier 3: change detection for the heavy sweep --------------------------


def _issue_body(failing: list[str], results: list, branch: str, ts: str) -> str:
    lines = [
        f"`repo-guardian` detected failing checks on `{branch}` at {ts}.",
        "",
        "**Failing checks:** " + ", ".join(failing),
        "",
    ]
    for name, ok, _dt, tail in results:
        if ok:
            continue
        lines.append(f"### {name}")
        lines.append("```")
        lines.extend(tail.splitlines() or ["(no output)"])
        lines.append("```")
    lines.append("")
    lines.append(
        "_Auto-filed by scripts/repo_guardian.py — auto-closes when the checks pass again._"
    )
    return "\n".join(lines)


def _find_open_issue(title: str) -> int | None:
    res = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "50",
            "--search",
            f'in:title "{title}"',
            "--json",
            "number,title",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    try:
        for it in json.loads(res.stdout or "[]"):
            if it.get("title") == title:
                return int(it["number"])
    except (json.JSONDecodeError, ValueError, KeyError):
        pass
    return None


def sync_github_issue(failing: list[str], results: list, branch: str, ts: str) -> None:
    """Keep one open issue per branch; create/comment on failure, close on recovery."""
    if not shutil.which("gh") or os.environ.get("REPO_GUARDIAN_NO_GH"):
        return
    title = f"[repo-guardian] check failures on {branch}"
    num = _find_open_issue(title)
    if failing:
        body = _issue_body(failing, results, branch, ts)
        if num is None:
            subprocess.run(
                ["gh", "issue", "create", "--title", title, "--body", body],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        else:
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "comment",
                    str(num),
                    "--body",
                    f"Failure state changed at {ts}:\n\n{body}",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
    elif num is not None:
        subprocess.run(
            [
                "gh",
                "issue",
                "comment",
                str(num),
                "--body",
                f"✅ All guardian checks green again at {ts}. Auto-closing.",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["gh", "issue", "close", str(num)], cwd=ROOT, capture_output=True, text=True
        )


def record_findings(results: list, branch: str) -> None:
    """Log + file an issue only when the set of failing checks changes (no spam)."""
    failing = sorted(name for name, ok, _dt, _tail in results if not ok)
    sig = "|".join(failing)
    last = LAST_SIG.read_text().strip() if LAST_SIG.exists() else ""
    if sig == last:
        return  # unchanged since last report — stay quiet
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with FINDINGS_LOG.open("a") as f:
        if failing:
            f.write(f"\n[{ts}] {branch} FAIL: {', '.join(failing)}\n")
            for name, ok, _dt, tail in results:
                if ok:
                    continue
                f.write(f"  --- {name} ---\n")
                for ln in tail.splitlines():
                    f.write(f"    {ln}\n")
        else:
            f.write(f"\n[{ts}] {branch} RECOVERED — all checks green\n")
    sync_github_issue(failing, results, branch, ts)
    LAST_SIG.write_text(sig)


def code_fingerprint() -> str:
    head = git("rev-parse", "HEAD")
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", "app", "tests", "scripts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout
    return hashlib.sha256((head + diff).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="force the heavy test sweep")
    ap.add_argument("--no-sweep", action="store_true", help="never run the heavy sweep")
    args = ap.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    results: list[tuple[str, bool, float, str]] = []

    print(f"== repo-guardian :: {branch} :: {PY} ==")

    # Tier 1: trust-plane guardian
    ok, dt, tail = run([PY, "scripts/demo_trust_plane.py", "--assert"], timeout=300)
    results.append(("trust-plane proof (prove-trust-plane)", ok, dt, tail))
    ok, dt, tail = run(["bash", "scripts/core_quality_gate.sh"], timeout=600)
    results.append(("core quality gate (ruff+mypy core)", ok, dt, tail))

    # Tier 2: readiness gap tracker
    try:
        cur = readiness_snapshot()
        prev = (
            json.loads(READINESS_SNAP.read_text()) if READINESS_SNAP.exists() else None
        )
        regressed, lines = diff_readiness(prev, cur)
        READINESS_SNAP.write_text(json.dumps(cur, indent=2))
        results.append(("readiness gap tracker", not regressed, 0.0, "\n".join(lines)))
    except Exception as exc:  # noqa: BLE001 - report, don't crash the loop
        results.append(("readiness gap tracker", False, 0.0, f"error: {exc}"))

    # Tier 4: CI / PR watcher
    if shutil.which("gh"):
        ok, dt, tail = run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                branch,
                "--limit",
                "3",
                "--json",
                "status,conclusion,workflowName,headSha",
            ],
            timeout=60,
        )
        if ok:
            try:
                runs = json.loads(tail)
                bad = [
                    r for r in runs if r.get("conclusion") not in (None, "success", "")
                ]
                summary = (
                    "; ".join(
                        f"{r['workflowName']}={r.get('conclusion') or r.get('status')}"
                        for r in runs
                    )
                    or "no recent runs"
                )
                results.append(("CI / PR watcher", not bad, dt, summary))
            except json.JSONDecodeError:
                results.append(("CI / PR watcher", True, dt, "no parseable runs"))
        else:
            results.append(
                ("CI / PR watcher", True, dt, f"gh unavailable: {tail[:120]}")
            )
    else:
        results.append(("CI / PR watcher", True, 0.0, "gh not installed - skipped"))

    # Tier 3: heavy test + lint sweep (gated on change unless forced)
    if not args.no_sweep:
        fp = code_fingerprint()
        last = (
            SWEEP_FINGERPRINT.read_text().strip() if SWEEP_FINGERPRINT.exists() else ""
        )
        if args.full or fp != last:
            why = "forced" if args.full else "code changed since last sweep"
            print(f"-- running heavy sweep ({why}) --")
            ok, dt, tail = run(
                [PY, "-m", "pytest", "tests/", "-q", "-p", "no:randomly"], timeout=900
            )
            results.append(("full test sweep (pytest -p no:randomly)", ok, dt, tail))
            ok2, dt2, tail2 = run(
                [PY, "-m", "ruff", "check", "app", "tests", "scripts"], timeout=300
            )
            results.append(("ruff (full)", ok2, dt2, tail2))
            if ok:  # only advance the fingerprint when the suite is green
                SWEEP_FINGERPRINT.write_text(fp)
        else:
            results.append(
                (
                    "full test sweep",
                    True,
                    0.0,
                    "skipped - no code change since last green sweep",
                )
            )

    # Summary
    print()
    failed = 0
    for name, ok, dt, tail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        dur = f"{dt:5.1f}s" if dt else "   -- "
        print(f"[{mark}] {dur}  {name}")
        if tail and (not ok or name.startswith("readiness")):
            for ln in tail.splitlines():
                print(f"         {ln}")
    print()
    verdict = "ALL GREEN" if failed == 0 else f"{failed} CHECK(S) FAILED"
    print(f"== repo-guardian: {verdict} ==")

    record_findings(results, branch)
    return failed


if __name__ == "__main__":
    sys.exit(main())
