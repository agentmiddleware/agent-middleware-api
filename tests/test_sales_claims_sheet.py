"""The sales claims sheet must stay within the documented trust boundary.

Regression guard for the security-as-selling-point slice: sellers stop at
tamper-evident and never say immutable, exactly-once, or compliant. If this
test fails, the sheet drifted past what the review kit and the limitations
doc support.
"""

from __future__ import annotations

from pathlib import Path

SHEET = Path(__file__).parent.parent / "docs" / "sales-claims-sheet.md"

BANNED_AFFIRMATIVE = (
    "immutable",
    "exactly-once",
    "exactly once",
    "compliant",
    "certified",
    "soc 2",
    "guaranteed delivery",
)

WARNED_WORDS = (
    "immutable",
    "exactly-once",
    "compliant",
    "guaranteed delivery",
)


def _sections() -> dict[str, str]:
    text = SHEET.read_text()
    sections: dict[str, str] = {}
    current = "preamble"
    chunks: dict[str, list[str]] = {current: []}
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            chunks[current] = []
        else:
            chunks[current].append(line)
    for name, lines in chunks.items():
        sections[name] = "\n".join(lines)
    return sections


def test_claims_sheet_lists_the_five_review_kit_claims():
    sections = _sections()
    claims = sections.get("The five claims you may make", "")
    for marker in (
        "Charge once under retry",
        "Budget is a cap",
        "delivery_uncertain",
        "verify offline",
        "Authority before money",
    ):
        assert marker in claims, f"claims sheet lost review-kit claim: {marker}"


def test_claims_section_makes_no_overclaim():
    sections = _sections()
    claims = sections.get("The five claims you may make", "").lower()
    for banned in BANNED_AFFIRMATIVE:
        assert banned not in claims, f"claims section overclaims: {banned}"


def test_claims_sheet_names_every_forbidden_word():
    sections = _sections()
    never = sections.get("Words you never use", "")
    assert never, "claims sheet lost its never-use section"
    for word in WARNED_WORDS:
        assert word in never.lower(), f"never-use section missing: {word}"


def test_claims_sheet_grounds_itself_in_review_kit_and_limits():
    text = SHEET.read_text()
    assert "security-review-kit.md" in text
    assert "SECURITY_LIMITATIONS.md" in text
    sections = _sections()
    assert any(name.startswith("The limits you must state") for name in sections), (
        "claims sheet lost its known-limits section"
    )
