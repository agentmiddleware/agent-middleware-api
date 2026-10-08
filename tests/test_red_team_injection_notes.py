"""Red-team injection notes must match the real transport posture.

The injection self-checks are simulated (they send no traffic), but their
report notes previously claimed deep JSON nesting is accepted and waved
stored XSS through as informational. The MCP transports actually refuse
nesting deeper than 100 levels before parsing, and the API serves JSON
only. These tests pin the honest notes.
"""

from __future__ import annotations

import pytest

from app.services.red_team import AttackEngine, InjectionAttacks


def _vector_named(fragment: str):
    matches = [
        vector
        for vector in InjectionAttacks.generate_vectors()
        if fragment in vector.name.lower()
    ]
    assert matches, fragment
    return matches[0]


@pytest.mark.anyio
async def test_json_bomb_note_names_real_depth_cap() -> None:
    result = await AttackEngine()._check_injection_defense(_vector_named("json bomb"))
    assert result.passed is True
    assert "100" in result.notes
    assert "Simulated" in result.notes
    assert "accepted" not in result.notes.lower()


@pytest.mark.anyio
async def test_xss_note_states_json_only_posture() -> None:
    result = await AttackEngine()._check_injection_defense(_vector_named("xss"))
    assert result.passed is True
    assert "JSON" in result.notes
    assert "Simulated" in result.notes
    assert "informational only" not in result.notes
