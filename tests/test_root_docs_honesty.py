"""Root-docs honesty for the GTM pitch slice (gtm-44).

WEDGE.md and ELEVATOR_PITCH.md are buyer-facing. Their headlines must use the
same "at most one" language the bodies enforce, so no headline can be quoted
as a stronger promise. The stale FINAL_SUMMARY.md verdict must stay archived
under docs/history/, and the pitch must name Sentinel as the human-approval
channel. File-read tests only: they must not boot the app.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_wedge_headline_uses_at_most_one_language():
    text = _read("WEDGE.md")
    lines = text.splitlines()
    title = lines[0].lower()
    assert "at-most-one" in title or "at most one" in title
    assert "exactly-once" not in title
    lead = "\n".join(lines[:12]).lower()
    assert "at most one" in lead
    assert "exactly-once" not in lead


def test_pitch_wedge_sentence_matches_body():
    text = _read("ELEVATOR_PITCH.md").lower()
    assert "at-most-one economic authorization" in text
    assert "at most one gateway" in text
    assert "exactly-once economic authorization" not in text


def test_pitch_names_sentinel_approval_channel():
    text = _read("ELEVATOR_PITCH.md")
    lowered = text.lower()
    assert "sentinel" in lowered
    assert "pauseapi.app" in lowered
    assert "human-approval-gate.md" in text
    assert "simulat" in lowered
    assert "not a standalone product" in lowered


def test_final_summary_stays_archived():
    assert not (ROOT / "FINAL_SUMMARY.md").exists()
    archived = ROOT / "docs" / "history" / "FINAL_SUMMARY.md"
    assert archived.exists()
    text = archived.read_text(encoding="utf-8").lower()
    assert "historical pr artifact, not maintained" in text
    assert "production-ready" in text and "not current claims" in text


def test_troubleshooting_uncertain_points_at_failure_semantics():
    text = _read("TROUBLESHOOTING.md")
    idx = text.find("delivery_uncertain")
    assert idx != -1
    section = text[idx : idx + 2000]
    assert "docs/failure-semantics.md" in section
    assert "docs/partner-first-tool-runbook.md" in section


def test_licensing_points_at_partner_pilot_shape():
    text = _read("LICENSING.md")
    assert "DESIGN_PARTNER_GUIDE.md" in text
