"""GTM slice gtm-79 product-line map: buyer-facing copy consistency guards.

These tests pin the small docs fixes from that review so a well-meaning edit
cannot silently soften a claim the gateway does not support. They read files
only and need no server, database, or keys.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEDGE_ONE_LINER = "Authorize one agent action. Charge it once. Prove what happened."


def _read(rel: str) -> str:
    # Collapse all whitespace so assertions are not sensitive to Markdown
    # line wrapping.
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def test_wedge_one_liner_frozen_everywhere() -> None:
    """The wedge one-liner must read identically on every buyer surface."""
    for rel in (
        "WEDGE.md",
        "README.md",
        "DEMO_SCRIPT.md",
        "DESIGN_PARTNER_GUIDE.md",
    ):
        assert WEDGE_ONE_LINER in _read(rel), f"one-liner missing from {rel}"


def test_money_page_states_the_honest_boundary() -> None:
    """The plain money page must say credits now, Stripe where present, and
    no settlement or payouts, and the README must point at it."""
    page = _read("docs/money-and-credits.md")
    for sentence in (
        "closed-loop metering unit",
        "Stripe",
        "No settlement",
        "No payouts",
        "settlement-rails.md",
    ):
        assert sentence in page, f"money page missing: {sentence}"
    # The page must not upgrade the claim with language the wedge forbids.
    assert "exactly-once" not in page.lower()
    assert "docs/money-and-credits.md" in _read("README.md")


def test_pilot_scope_stated_up_front_in_partner_guide() -> None:
    """The design partner guide must state the pilot limits before any
    technical content, matching SECURITY_LIMITATIONS.md."""
    guide = _read("DESIGN_PARTNER_GUIDE.md")
    for sentence in (
        "one vendor-managed Railway project per customer",
        "synthetic or redacted",
        "PHI",
        "not supported in this pilot",
        "SECURITY_LIMITATIONS.md",
    ):
        assert sentence in guide, f"partner guide missing: {sentence}"


def test_sentinel_positioned_as_optional_integration() -> None:
    """Human approval must be described as an optional integration with an
    external service, never as a standalone product line."""
    assert "not a standalone product" in _read("README.md")
    index = _read("docs/README.md")
    assert "human-approval-gate.md" in index
    assert "not a standalone product" in index


def test_python_sdk_marked_recommended_over_wrappers() -> None:
    """The docs index must name one recommended client path and label the
    framework wrappers as source-only examples."""
    index = _read("docs/README.md")
    assert "recommended client path" in index
    assert "source-only integration examples" in index
