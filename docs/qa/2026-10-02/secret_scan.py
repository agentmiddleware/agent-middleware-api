"""Run redacted Gitleaks over tracked source, excluding credential/env files."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    excluded = []
    count = 0
    # Preserve this private temporary snapshot for reproducibility; no repository files removed.
    snapshot = Path(tempfile.mkdtemp(prefix="amw-qa-source-scan-", dir="/private/tmp"))
    for name in files:
        if not name:
            continue
        path = Path(name)
        if (
            any(part.startswith(".env") for part in path.parts)
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite"}
            or path.name.lower() in {"credentials", "credentials.json", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"}
            or ".aws" in path.parts
        ):
            excluded.append(name)
            continue
        source = root / path
        if not source.is_file() or source.is_symlink():
            continue
        target = snapshot / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        count += 1
    report = root / "docs/qa/2026-10-02/artifacts/tracked-secret-scan-relative.json"
    result = subprocess.run(
        # Relative paths preserve the repository's existing anchored allowances.
        ["gitleaks", "dir", ".", "--config", ".gitleaks.toml", "--redact=100", "--no-banner", "--no-color", "--report-format", "json", "--report-path", str(report)],
        cwd=snapshot,
        check=False,
    )
    entries = json.loads(report.read_text()) if report.exists() else []
    # The raw redacted scanner report is narrowed to location/rule only as defense in depth.
    findings = [
        {
            "file": item.get("File", "").removeprefix(str(snapshot) + "/"),
            "line": item.get("StartLine"),
            "rule": item.get("RuleID"),
            "value": "[REDACTED]",
        }
        for item in entries
    ]
    output = {
        "scope": "Tracked working-tree files, current content, no history or environment/credential files",
        "files_scanned": count,
        "excluded_files": excluded,
        "exit_code": result.returncode,
        "findings": findings,
    }
    report.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
