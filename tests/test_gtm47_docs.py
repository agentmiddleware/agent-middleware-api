"""GTM-47 docs slice: plan status headers and buyer-clarity notes.

These tests pin the small docs fixes from the gtm-47-api-docs-research slice:
Phase 9 plans must carry a status header so readers stop guessing what is
done, the duplicate-guard sales note must state the enforce story and its
limits, the Sentinel gate doc must name pilot prerequisites, and the archived
probe README must say its output is a regeneration that cannot be cited as
current.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_phase9_blueprint_has_status_header():
    text = _read(".opencode/plans/PHASE9_BLUEPRINT.md")
    assert "Status:" in text
    assert "app/routers/discover.py" in text


def test_phase9_discoverability_plan_has_status_header():
    text = _read(".opencode/plans/PHASE9_DOT1_DISCOVERABILITY.md")
    assert "Status:" in text
    assert "app/routers/discover.py" in text


def test_duplicate_guard_guidance_states_enforce_story_and_limits():
    text = _read("docs/duplicate-guard-guidance.md")
    for phrase in (
        "MCP_UPSTREAM_DUPLICATE_GUARD",
        "enforce",
        "log",
        "Same permit only",
        "Identical arguments only",
        "Upstream tools only",
        "allow_identical_repeats",
        "24 hours",
    ):
        assert phrase in text, phrase


def test_policy_enforcement_links_guard_guidance():
    text = _read("docs/POLICY_ENFORCEMENT.md")
    assert "duplicate-guard-guidance.md" in text


def test_human_approval_gate_names_pilot_prerequisites():
    text = _read("docs/human-approval-gate.md")
    assert "Pilot prerequisites" in text
    assert "SENTINEL_API_URL" in text
    assert "SENTINEL_API_KEY" in text
    assert "SIMULATION_MODE_HUMAN_APPROVAL=false" in text


def test_archived_probe_readme_discloses_regeneration():
    text = _read("docs/research/external-adversarial-2026-09-11/README.md")
    assert "2026-09-14 regeneration" in text
    assert "not retained" in text
    assert "cannot be re-run or cited as current" in text
