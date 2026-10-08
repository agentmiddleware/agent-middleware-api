"""Test that CI proves the production posture on PostgreSQL, not just SQLite.

The default suite runs on SQLite with permissive trust flags, postgres_trust
proves Postgres with permissive flags, and production_trust proves strict
flags on SQLite. None proves the combination buyers run. The
``production_parity`` CI job must keep combining strict production trust
flags with a real PostgreSQL backend.

Regression style: if the job is deleted, loses its Postgres service, drops
a strict flag, or stops running the trust-primitive files, this test fails.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_CONFIG = ROOT / ".github" / "workflows" / "ci.yml"

# Flags that define the production posture (see
# app/core/trust_mode.py::validate_trust_mode_config). ENVIRONMENT stays
# "test" because the Postgres-gated action tests refuse any other value
# (see tests/support/action_database_guard.py); everything else is strict.
_REQUIRED_ENV = (
    'TRUST_MODE_ENABLED: "true"',
    'ALLOW_LEGACY_UNPERMITTED_MCP: "false"',
    'ENABLE_PROOF_SURFACES: "false"',
    'DEBUG: "false"',
    'WEBAUTHN_ALLOW_MOCK: "false"',
    "TRUST_SIGNING_PRIVATE_KEY_B64:",
    "STATE_BACKEND: postgres",
    "DATABASE_URL: postgresql+asyncpg://",
    'REQUIRE_POSTGRES_TESTS: "1"',
)

# Every behavior file the parity job must keep running. If a file is
# removed here, it must also leave the CI job in the same change. This is
# the trust core, verified locally under the job's strict-on-Postgres env
# (83 passed); the full suite assumes permissive defaults by design, so it
# cannot run here.
_REQUIRED_TEST_FILES = (
    "tests/test_permits.py",
    "tests/test_receipts.py",
    "tests/test_mcp_trust.py",
    "tests/test_audit_chain.py",
    "tests/test_key_management.py",
    "tests/test_idempotency.py",
    "tests/test_security_fuzz_battery.py::test_rapid_fire_invokes_all_accounted",
)


def _parity_job_block() -> str:
    """Return the raw text of the production_parity job in ci.yml."""
    text = CI_CONFIG.read_text()
    starts = [m.start() for m in re.finditer(r"(?m)^  [A-Za-z0-9_]+:\s*$", text)]
    assert starts, "no top-level jobs found in ci.yml"
    names = [re.match(r"  ([A-Za-z0-9_]+):", text[s:]).group(1) for s in starts]
    assert "production_parity" in names, (
        "CI must keep a production_parity job running the suite with "
        "production settings on Postgres"
    )
    begin = starts[names.index("production_parity")]
    end = min([s for s in starts if s > begin], default=len(text))
    return text[begin:end]


def test_production_parity_job_runs_on_postgres_service():
    block = _parity_job_block()
    assert "image: postgres:" in block, (
        "production_parity must run against a Postgres service container"
    )
    assert "alembic upgrade head" in block, (
        "production_parity must migrate the Postgres database before testing; "
        "Postgres never gets ephemeral create_all"
    )


def test_production_parity_job_keeps_strict_production_flags():
    block = _parity_job_block()
    for flag in _REQUIRED_ENV:
        assert flag in block, (
            f"production_parity lost its production posture: {flag!r} missing"
        )
    assert 'TRUST_MODE_ENABLED: "false"' not in block
    assert 'ALLOW_LEGACY_UNPERMITTED_MCP: "true"' not in block
    config_lines = [
        line for line in block.splitlines() if not line.strip().startswith("#")
    ]
    assert "sqlite" not in "\n".join(config_lines).lower(), (
        "production_parity must not fall back to SQLite anywhere in the job"
    )


def test_production_parity_job_runs_trust_and_concurrency_files():
    block = _parity_job_block()
    for path in _REQUIRED_TEST_FILES:
        assert path in block, (
            f"production_parity stopped running {path}; the strict-on-Postgres "
            "proof silently shrank"
        )


def test_production_parity_job_does_not_run_the_whole_suite():
    """The full suite assumes permissive defaults, so a bare tests/ run here
    would fail for reasons unrelated to production behavior."""
    block = _parity_job_block()
    assert not re.search(r"(?m)^\s*run:\s*pytest tests/\s", block), (
        "production_parity must run named trust files, not the whole suite"
    )
