"""Guards for the 5-minute quickstart contract (docs/quickstart.md).

The core loop (boot, key, permit, invoke, replay, offline verify) must read
as a five minute path with the overspend, authority, and MCP-client material
marked as follow-ons, and README must describe it that way. The full
command-by-command behavior is guarded by tests/test_quickstart_path.py;
this file guards the shape a newcomer sees first.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "docs" / "quickstart.md"
README = REPO_ROOT / "README.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_core_loop_promises_five_minutes() -> None:
    text = _text(QUICKSTART)
    assert "about five minutes" in text
    assert "five minute core loop" in text


def test_follow_ons_come_after_the_core_loop() -> None:
    text = _text(QUICKSTART)
    core_end = text.index("five minute core loop")
    follow_ons = text.index("## Follow-ons")
    overspend = text.index("## 8. Overspend on purpose")
    assert follow_ons < overspend
    assert core_end < follow_ons
    assert "(follow-on" in text.split("## 9.")[1].split("\n")[0]
    assert "(follow-on" in text.split("## 10.")[1].split("\n")[0]


def test_core_commands_are_present() -> None:
    blocks = re.findall(r"```bash\n(.*?)```", _text(QUICKSTART), re.S)
    joined = "\n".join(blocks)
    for signature in (
        "make quickstart",
        "/v1/dev-keys/self-provision",
        "/v1/permits",
        '\\"max_credits\\": 7',
        "/mcp/messages",
        '\\"idempotency_key\\": \\"quickstart-note-1\\"',
        "/v1/receipts/$RECEIPT_ID/portable",
        "verify_cli",
        "forged-receipt.json",
    ):
        assert signature in joined, signature


def test_readme_describes_the_five_minute_path() -> None:
    text = _text(README)
    assert "docs/quickstart.md" in text
    assert "five minutes" in text


def test_quickstart_makes_no_exactly_once_claim() -> None:
    text = _text(QUICKSTART).lower()
    assert "exactly-once" not in text
    assert "exactly once" not in text
