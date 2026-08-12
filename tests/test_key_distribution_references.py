"""Guard against key-distribution reference drift.

The Hard Run Report (P1-B) found surfaces that pointed agents and humans at
``/.well-known/jwks.json`` for offline verification — an endpoint that returns
404. The real, served anchor is ``/.well-known/trust-keys.json``. A reader who
follows a stale reference lands on a 404 at the core of the "verify it yourself,
offline" story, so these references must not regress.

This test pins the trust-plane surfaces that tell an outside party where to
fetch the signing keys. It intentionally does NOT scan the whole tree: the Hard
Run Report itself quotes the broken path as its finding, which is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKING_ENDPOINT = "/.well-known/trust-keys.json"
DEAD_ENDPOINT = "/.well-known/jwks.json"

# Surfaces that direct a verifier to the published key document. Each must name
# the working endpoint and must not name the 404 one.
KEY_DISTRIBUTION_SOURCES = (
    "app/services/quotes.py",
    "docs/signed-quotes.md",
    "docs/agent-accountability.md",
    "b2a_sdk/src/b2a_sdk/verify_cli.py",
)


@pytest.mark.parametrize("relative_path", KEY_DISTRIBUTION_SOURCES)
def test_source_points_at_the_served_key_endpoint(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert DEAD_ENDPOINT not in text, (
        f"{relative_path} references {DEAD_ENDPOINT}, which returns 404; "
        f"use {WORKING_ENDPOINT} (Hard Run Report P1-B)."
    )
    assert WORKING_ENDPOINT in text, (
        f"{relative_path} should name the served key endpoint "
        f"{WORKING_ENDPOINT} so an outside party can verify offline."
    )
