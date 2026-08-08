"""Guards the first five minutes of a new user's experience.

Each assertion here corresponds to a failure that a skeptic actually hit when
following the documented setup: copy `.env.example`, start the API, run the
gates. These are cheap to re-break in a docs edit, so they are pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.main import (
    _SIGNING_KEY_REMEDIATION,
    _SIGNING_KEY_REMEDIATION_DEFAULT,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _uncommented_assignments() -> dict[str, str]:
    """Parse `.env.example` the way `cp .env.example .env` + a loader would."""

    values: dict[str, str] = {}
    for raw in ENV_EXAMPLE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def test_signing_seed_is_a_visible_required_key() -> None:
    """The seed is required in every environment, so it must not be buried.

    It previously appeared only inside a commented-out block labelled
    "production checklist", so copying the file and starting the API failed with
    `trust_signing_private_key_required`.
    """

    assignments = _uncommented_assignments()
    assert "TRUST_SIGNING_PRIVATE_KEY_B64" in assignments, (
        "TRUST_SIGNING_PRIVATE_KEY_B64 must be an uncommented key in "
        ".env.example: TRUST_MODE_ENABLED defaults to true, so the app cannot "
        "start without it."
    )


def test_signing_seed_ships_empty_rather_than_with_a_real_value() -> None:
    assignments = _uncommented_assignments()
    assert assignments["TRUST_SIGNING_PRIVATE_KEY_B64"] == "", (
        ".env.example must never carry real or placeholder key material; "
        "operators fill it from the documented generation command."
    )


def test_env_example_documents_how_to_generate_the_seed() -> None:
    text = ENV_EXAMPLE.read_text()
    assert "secrets.token_bytes(32)" in text, (
        ".env.example must include the seed generation command inline — telling "
        "a user a value is required without telling them how to produce it is "
        "the failure this guards."
    )


def test_default_state_backend_boots_locally() -> None:
    """Defaults must not be a placeholder PostgreSQL DSN under ENVIRONMENT=local.

    That combination previously failed startup with `socket.gaierror` because
    the example host does not resolve.
    """

    assignments = _uncommented_assignments()
    assert assignments.get("ENVIRONMENT") == "local"

    database_url = assignments.get("DATABASE_URL", "")
    assert database_url, "DATABASE_URL must have a working default"
    assert "user:password@host" not in database_url, (
        "DATABASE_URL default is an unresolvable placeholder; a fresh copy of "
        ".env.example must boot without hand-editing the datastore."
    )
    assert database_url.startswith("sqlite"), (
        "the shipped default should be the local SQLite path documented in the "
        "README; PostgreSQL belongs in the commented production block"
    )
    assert assignments.get("STATE_BACKEND") == "sqlite"


@pytest.mark.parametrize(
    "error_code",
    ["trust_signing_private_key_required", "invalid_trust_signing_private_key"],
)
def test_signing_key_failures_carry_actionable_remediation(error_code: str) -> None:
    """A failed first boot must say how to fix itself, not just what broke."""

    remediation = _SIGNING_KEY_REMEDIATION[error_code]
    assert "TRUST_SIGNING_PRIVATE_KEY_B64" in remediation
    assert "secrets.token_bytes(32)" in remediation, (
        "remediation must include the exact command that produces a valid seed"
    )


def test_remediation_lookup_has_a_safe_default() -> None:
    assert _SIGNING_KEY_REMEDIATION_DEFAULT
    assert "TRUST_SIGNING_PRIVATE_KEY_B64" in _SIGNING_KEY_REMEDIATION_DEFAULT
