"""Read-only audit of another task's retained local validation evidence.

Does not execute application tests, import application code, read environment
files, or connect to a database. Hash equality binds files to the retained
manifest; it does not authenticate the test executor or prove the software.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(source: Path, evidence: Path) -> dict:
    acceptance_manifest = evidence / "logs/acceptance-source-manifest.json"
    manifest_path = (
        acceptance_manifest
        if acceptance_manifest.is_file()
        else evidence / "logs/final-source-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    comparisons = []
    for root in [source, *map(Path, manifest["tested_roots"])]:
        missing, mismatches = [], []
        for entry in manifest["entries"]:
            candidate = root / entry["path"]
            if not candidate.is_file():
                missing.append(entry["path"])
            elif digest(candidate) != entry["tested_sha256"]:
                mismatches.append(entry["path"])
        comparisons.append(
            {
                "root": str(root),
                "matched": len(manifest["entries"]) - len(missing) - len(mismatches),
                "missing": missing,
                "mismatches": mismatches,
            }
        )

    log_names = [
        "acceptance-full.log",
        "acceptance-regressions.log",
        "acceptance-poolone.log",
        "acceptance-multiprocess.log",
        "acceptance-concurrency.log",
        "acceptance-datetime.log",
        "acceptance-production.log",
        "acceptance-trust.log",
        "acceptance-ruff.log",
        "acceptance-mypy.log",
        # Historical failures are retained so the acceptance result does not
        # erase the reliability defect that caused the earlier hold.
        "final-postgres-rapidfire.log",
        "baseline-postgres-rapidfire.log",
    ]
    logs = []
    for name in log_names:
        path = evidence / "logs" / name
        if not path.is_file():
            logs.append({"path": str(path), "exists": False})
            continue
        # Persist only result lines, never raw request output or configuration.
        result_lines = []
        for line in path.read_text().splitlines():
            if (
                re.match(r"^\d+ (?:passed|failed)(?:,| in )", line)
                or line.startswith("FAILED ")
                or "QueuePool limit" in line
                or line == "All checks passed!"
                or line.startswith("Success: no issues found")
                or line == "[trust-gate] trust release gate passed"
            ):
                result_lines.append(line)
        logs.append(
            {
                "path": str(path),
                "exists": True,
                "sha256": digest(path),
                "results": result_lines,
            }
        )

    baseline_path = Path(__file__).with_name("baseline-manifest.json")
    baseline = json.loads(baseline_path.read_text())
    changed_since_baseline = []
    for rel, expected in baseline["files"].items():
        current = source / rel
        if not current.is_file() or digest(current) != expected:
            changed_since_baseline.append(rel)

    acceptance_commands = evidence / "logs/acceptance-command-manifest.json"
    command_path = (
        acceptance_commands
        if acceptance_commands.is_file()
        else evidence / "logs/final-command-manifest.json"
    )
    command_summary = None
    if command_path.is_file():
        commands = json.loads(command_path.read_text())
        command_summary = {
            "path": str(command_path),
            "sha256": digest(command_path),
            "status": commands.get("status"),
            "runs": [
                {
                    key: run.get(key)
                    for key in (
                        "id",
                        "cwd",
                        "environment_cleared",
                        "exit_code",
                        "status",
                        "result",
                        "log_sha256",
                        "source_verified_before",
                        "source_verified_after",
                    )
                }
                for run in commands.get("commands", commands.get("runs", []))
            ],
            "scope": "Summary only; environments, argv and shell strings are not copied. Executor supplied command history, not an independent execution attestation.",
        }

    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "Independent read-only file hashes and retained result-line inspection; no app tests run by this audit.",
        "limitations": [
            "Concurrent tasks can change source after capture; this is not a source freeze.",
            "The manifest is a scoped inventory, not every local file or a signed attestation.",
            "Result rows overlap; never add them into a unique-test total.",
            "Logs establish local synthetic observations, not customer or production validation.",
            "Missing test cases, excluded markers, and environment differences still matter.",
        ],
        "manifest": {
            "path": str(manifest_path),
            "sha256": digest(manifest_path),
            "entries": len(manifest["entries"]),
        },
        "base_commit_context": manifest["base_commit_context"],
        "source_comparisons": comparisons,
        "all_manifest_files_match": all(
            not row["missing"] and not row["mismatches"] for row in comparisons
        ),
        "files_changed_since_this_review_started": changed_since_baseline,
        "test_results_owned_by": "Existing launch engineering task 01a056df-ba0b-7472-b6cc-747dccc8cdd9",
        "command_manifest": command_summary,
        "logs": logs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument(
        "--evidence", type=Path, default=Path("/tmp/amw-launch-20260831")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("technical-evidence.json"),
    )
    parser.add_argument(
        "--allow-source-drift",
        action="store_true",
        help="Record current source mismatches without returning a failing status.",
    )
    args = parser.parse_args()
    result = audit(args.source, args.evidence)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "entries": result["manifest"]["entries"],
                "all_manifest_files_match": result["all_manifest_files_match"],
            }
        )
    )
    if not result["all_manifest_files_match"] and not args.allow_source_drift:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
