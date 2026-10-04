"""Enumerate claim candidates from tracked text without reading credential files."""

import json
from pathlib import Path
import re
import subprocess

from run_logged import scrub


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PATTERN = re.compile(
    r"exactly[\s\-\u2010-\u2015]+once"
    r"|(?:new|different|fresh).{0,70}idempotency"
    r"|idempotency.{0,70}(?:new|different|fresh)"
    r"|duplicate.guard|duplicate_request_new_key"
    r"|(?:new|fresh)[ -]key.{0,140}(?:refus|dedup|block|reject)"
    r"|(?:refus|dedup|block|reject).{0,140}(?:new|fresh)[ -]key",
    re.I,
)


def family(name, line, text):
    if (
        name == "docs/agent-self-credentialing.md"
        or (name == "docs/tool-interface-authority.md" and line == 37)
        or (name == "ELEVATOR_PITCH.md" and line in (115, 162, 164))
    ):
        return "BE-100", "Integration guidance: read BE-100 context and defect"
    if name.startswith(("tests/", "scripts/", "failure_lab/", "wrappers/")):
        return "BE-109", "Test, scenario or helper reference; not a universal guarantee"
    if name.startswith(("site/arcade", "migrations/", ".railway/", ".github/")):
        return "BE-109", "Supporting/configuration/historical/game reference"
    if name in ("app/schemas/iot.py", "app/services/mcp_phase9_tools.py"):
        return "BE-109", "QoS vocabulary or local registration; not gateway delivery"
    if "refund" in text.lower() or name == "app/services/permits.py":
        return (
            "BE-107",
            "Scoped refund/reservation property; runtime proof not rerun here",
        )
    if name in (
        "app/services/permit_requests.py",
        "docs/permit-requests.md",
        "app/services/human_approval.py",
    ):
        return (
            "BE-108",
            "Permit/approval issuance identity; external notification not proved",
        )
    if re.search(r"new|fresh|duplicate|repeat", text, re.I):
        return (
            "BE-103/104/105",
            "Cross-key/default/enforce scope; see report for exact boundaries",
        )
    if name in ("docs/PROOF_MATRIX.md", "DEMO_SCRIPT.md", "DESIGN_PARTNER_GUIDE.md"):
        return (
            "BE-106/102",
            "Controlled proof or downstream limitation; not general delivery",
        )
    if re.search(r"remote|downstream|upstream|side.effect", text, re.I):
        return (
            "BE-102",
            "Remote-effect qualifier or negation; upstream support remains required",
        )
    if name.startswith("CHANGELOG") or "report" in name or "checkpoint" in name:
        return (
            "BE-109",
            "Historical/result reference; historical pass count not refreshed",
        )
    return (
        "BE-101/109",
        "Same-key scoped claim or reference; inspect linked family evidence",
    )


def main():
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    rows = []
    excluded = 0
    unreadable = 0
    for name in tracked:
        if not name:
            continue
        path = ROOT / name
        if (
            any(
                part.startswith(".env")
                or part in {"node_modules", ".git", ".venv", ".aws", ".ssh"}
                for part in path.parts
            )
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
            or path.name.lower()
            in {
                "credentials",
                "credentials.json",
                "credentials.toml",
                "credential-store.json",
                "secret-store.json",
                "token-cache.json",
                "private_key",
                "id_rsa",
                "id_ed25519",
                "id_dsa",
                "id_ecdsa",
            }
        ):
            excluded += 1
            continue
        if not path.is_file():
            unreadable += 1
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, text in enumerate(lines, 1):
            if PATTERN.search(text):
                group, status = family(name, number, text)
                rows.append(
                    {
                        "id": f"BE-C{len(rows) + 1:03}",
                        "file": name,
                        "line": number,
                        "text": scrub(text.strip()),
                        "finding_family": group,
                        "status": status,
                    }
                )
    (HERE / "artifacts" / "claims-inventory.json").write_text(
        json.dumps(rows, indent=2) + "\n"
    )
    heading = (
        "# Claim occurrence inventory\n\n"
        "PR: opened by orchestrator\n\nCI status: pending at time of writing\n\n"
        f"{len(rows)} lexical occurrences in {len({row['file'] for row in rows})} tracked files. "
        f"{excluded} environment/key/credential-store paths excluded; {unreadable} tracked paths absent. "
        "The search includes Unicode hyphens, new/fresh key refusal language, and duplicate-guard references. "
        "It reads tracked UTF-8 text only; it does not open environment or credential-store files. "
        "Source code and documentation discussing secrets or credentials remain in scope.\n\n"
        "These are recorded claim candidates, including correct claims, disclaimers, code identifiers, tests, "
        "historical reports and non-delivery uses. Family assignments are a navigation aid, not a claim of "
        "independent runtime verification of each row. Read [CLAIMS-REPORT.md](CLAIMS-REPORT.md) for manual "
        "implementation tracing, defect BE-100 and explicit limits. Non-defect rows do not enter severity counts. "
        "Search cannot prove absence of an arbitrarily paraphrased claim.\n\n"
        "| Occurrence | Source | Exact matched line | Family | Classification |\n"
        "|---|---|---|---|---|\n"
    )

    def escape(value):
        # Quoted source Markdown must not become links relative to this report.
        # Preserve the exact source in JSON; entities render literal brackets here.
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("|", "\\|")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("[", "&#91;")
            .replace("]", "&#93;")
        )

    lines = [heading]
    for row in rows:
        source = f"`{row['file']}:{row['line']}`"
        lines.append(
            "| "
            + " | ".join(
                [
                    row["id"],
                    source,
                    escape(row["text"]),
                    row["finding_family"],
                    row["status"],
                ]
            )
            + " |\n"
        )
    (HERE / "CLAIMS-INVENTORY.md").write_text("".join(lines))
    print(
        f"Enumerated {len(rows)} occurrences in {len({r['file'] for r in rows})} tracked files."
    )
    print(
        f"Excluded environment/key/credential-store paths: {excluded}; absent tracked files: {unreadable}."
    )
    print(
        "Wrote CLAIMS-INVENTORY.md and artifacts/claims-inventory.json; content scrubbed."
    )


if __name__ == "__main__":
    main()
