"""Include every independent group log in the required aggregate session log."""

from pathlib import Path
import re


def assemble():
    here = Path(__file__).resolve().parent
    target = here / "SESSION-LOG.md"
    marker = "\n<!-- CONSOLIDATED COMMAND RECORDS -->\n"
    preamble = target.read_text().split(marker, 1)[0].rstrip()
    sections = []
    for name in ("COORDINATION", "BACKEND", "CLAIMS", "FRONTEND", "UX", "GATE"):
        source = here / f"{name}-SESSION.md"
        if source.exists():
            content = source.read_text().strip()
            # Long commands can finish after another command header was appended.
            # The artifact stem identifies the outcome's command unambiguously.
            content = re.sub(
                r"(?m)^Outcome: (.*?\[Output\]\(artifacts/([^/)]+)\.txt\)\.)$",
                lambda match: f"Outcome for `{match.group(2)}`: {match.group(1)}",
                content,
            )
            sections.append(
                f"\n## Consolidated {name.lower()} record\n\n" + content + "\n"
            )
    target.write_text(preamble + "\n" + marker + "".join(sections))


if __name__ == "__main__":
    assemble()
