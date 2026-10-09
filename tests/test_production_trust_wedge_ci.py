"""Guard for the strict-trust wedge CI step.

The default suite runs in permissive trust mode (see tests/conftest.py):
legacy unpermitted MCP is allowed back in, every test shares one fixed API
key, and the rate limit is a million per minute. A bug that only appears
under strict trust flags therefore passes the whole suite except for the
few tests that flip strict mode back on.

The ``production_trust`` CI job must run the core wedge tests (permits,
idempotency, governed dispatch, debits, receipts) under strict trust flags
to close that gap. This test parses the workflow file and fails if that
step goes missing or loses its strict flags, so deleting the step turns
the suite red instead of silently dropping the coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Wedge money-path tests verified green under strict trust flags
# (TRUST_MODE_ENABLED=true, ALLOW_LEGACY_UNPERMITTED_MCP=false, plus a
# test signing key). Keep this list identical to the step in ci.yml.
STRICT_WEDGE_TEST_FILES = (
    "tests/test_idempotency.py",
    "tests/test_mcp_trust.py",
    "tests/test_mcp_trust_mode.py",
    "tests/test_mcp_upstream_governed.py",
    "tests/test_permits.py",
    "tests/test_receipts.py",
    "tests/test_refund_reconciliation.py",
)


def _is_job_header(line: str) -> bool:
    stripped = line.strip()
    return (
        line.startswith("  ")
        and not line.startswith("   ")
        and stripped.endswith(":")
        and " " not in stripped
    )


def _production_trust_block() -> str:
    lines = CI_WORKFLOW.read_text().splitlines()
    start = next(
        index for index, line in enumerate(lines) if line == "  production_trust:"
    )
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if _is_job_header(lines[index])
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_ci_runs_wedge_tests_under_strict_trust_flags():
    block = _production_trust_block()
    assert 'TRUST_MODE_ENABLED: "true"' in block
    assert 'ALLOW_LEGACY_UNPERMITTED_MCP: "false"' in block
    assert "TRUST_SIGNING_PRIVATE_KEY_B64" in block
    for test_file in STRICT_WEDGE_TEST_FILES:
        assert test_file in block, test_file


def test_strict_wedge_step_restores_production_rate_limit():
    """The step must not inherit conftest's million-per-minute limit."""
    block = _production_trust_block()
    assert "RATE_LIMIT_PER_MINUTE" in block
    assert "1000000" not in block


@pytest.mark.parametrize("test_file", STRICT_WEDGE_TEST_FILES)
def test_strict_wedge_test_file_exists(test_file):
    assert (REPO_ROOT / test_file).is_file()
