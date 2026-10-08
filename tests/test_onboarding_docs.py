"""Docs consistency guard for the onboarding path.

The onboarding review found the operator golden path used a tool name
(``golden-path-echo``) that does not exist on a stock server, buried the
substitution note, numbered two different sections ``7``, and listed
dormant dry-run/velocity steps as success criteria. It also found the
quickstart replayed the original receipt on re-runs with the reset note
easy to miss. These tests pin the fixed shape so the docs cannot drift
back: sequential step numbers, stock-server tool defaults, dormant steps
labeled as such, and a reset pointer where the replay happens.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "docs" / "golden-path.md"
QUICKSTART = REPO_ROOT / "docs" / "quickstart.md"
STOCK_TOOL = "partner.notes.write"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_golden_path_steps_numbered_sequentially():
    headings = re.findall(r"^## (\d+)\. ", _text(GOLDEN_PATH), re.MULTILINE)
    numbers = [int(n) for n in headings]
    assert numbers, "no numbered steps found in docs/golden-path.md"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"steps must run 1..N with no gaps or duplicates, got {numbers}"
    )


def test_golden_path_has_no_suffixed_step_numbers():
    suffixed = re.findall(r"^## \d+[a-z]\. ", _text(GOLDEN_PATH), re.MULTILINE)
    assert suffixed == [], f"renumber suffixed steps instead: {suffixed}"


def _invoke_names(text: str) -> list[str]:
    # Tool names from tools/call blocks only. The doc escapes JSON quotes
    # inside shell blocks (\"name\"), so match both escaped and plain forms.
    # A bare search would also catch the wallet-policy "name" field, which
    # is not a tool invocation.
    calls = re.split(r'\\?"method\\?": \\?"tools/call\\?"', text)
    names = []
    for chunk in calls[1:]:
        match = re.search(r'\\?"name\\?": \\?"([^"\\]+)\\?"', chunk[:2000])
        if match:
            names.append(match.group(1))
    return names


def test_golden_path_invokes_stock_tool_by_default():
    text = _text(GOLDEN_PATH)
    invoke_names = _invoke_names(text)
    assert invoke_names, "no invoke examples found in docs/golden-path.md"
    assert invoke_names[0] == STOCK_TOOL, (
        f"first invoke example must use the stock tool {STOCK_TOOL}, "
        f"got {invoke_names[0]}"
    )


def test_golden_path_names_operator_tool_only_as_variant():
    text = _text(GOLDEN_PATH)
    assert "golden-path-echo" in text, (
        "the operator-registered tool variant should still be documented"
    )
    invoke_names = _invoke_names(text)
    assert "golden-path-echo" not in invoke_names, (
        "invoke examples must default to the stock tool; keep "
        "golden-path-echo to prose describing the operator variant"
    )


def test_golden_path_dormant_steps_say_so():
    text = _text(GOLDEN_PATH)
    for marker in ("ENABLE_PROOF_SURFACES=true", "dormant"):
        assert marker in text, (
            f"docs/golden-path.md must label dormant steps ({marker})"
        )


def test_quickstart_replay_points_at_reset():
    text = _text(QUICKSTART)
    assert "--reset" in text, "docs/quickstart.md must document the reset flag"
    replay_pos = text.find("replays the *original* receipt")
    assert replay_pos != -1, "replay warning missing from docs/quickstart.md"
    assert (
        "Starting over" in text[: replay_pos + 2000]
        or "--reset" in text[replay_pos : replay_pos + 2000]
    ), "replay warning must point at the reset path"


def test_quickstart_points_at_helper_script():
    text = _text(QUICKSTART)
    assert "scripts/first_credential.py" in text, (
        "docs/quickstart.md must point newcomers at the helper script"
    )
