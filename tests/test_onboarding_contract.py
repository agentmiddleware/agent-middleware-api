"""Guards the first five minutes of a new user's experience.

Each assertion here corresponds to a failure that a skeptic actually hit when
following the documented setup: copy `.env.example`, start the API, run the
gates. These are cheap to re-break in a docs edit, so they are pinned.
"""

from __future__ import annotations

import re
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


# --- Documentation honesty -------------------------------------------------
#
# `tests/test_wedge_honesty.py` already guards the runtime discovery surfaces
# (`agent.json`, `/llm.txt`) against advertising unpublished installs. These
# extend the same rule to the docs, READMEs, and examples a reader copies from.

#: Distributions this repository builds but does NOT publish to any index.
#: Every one of these was documented as a plain `pip install <name>` that exits
#: 1 with "No matching distribution found".
UNPUBLISHED_DISTRIBUTIONS = (
    "agent-middleware-api",
    "agent-middleware-awi",
    "langchain-agent-middleware",
    "crewai-agent-middleware",
    "autogen-agent-middleware",
    "b2a-sdk",
)

#: Paths excluded from the docs sweep: vendored/marketing site content, and the
#: two files whose whole job is to record or assert these strings.
_DOC_SWEEP_EXCLUDES = (
    "site/",
    "node_modules/",
    "tests/test_wedge_honesty.py",
    "tests/test_onboarding_contract.py",
    "docs/tech-debt-remediation-plan.md",
)


def _sweepable_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.md", "*.py"):
        for path in REPO_ROOT.rglob(pattern):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(rel.startswith(x) or rel == x for x in _DOC_SWEEP_EXCLUDES):
                continue
            if "/.venv/" in f"/{rel}" or rel.startswith(".venv/"):
                continue
            files.append(path)
    return files


@pytest.mark.parametrize("distribution", UNPUBLISHED_DISTRIBUTIONS)
def test_docs_do_not_advertise_unpublished_installs(distribution: str) -> None:
    """No doc may tell a reader to `pip install` something that does not exist."""

    needle = f"pip install {distribution}"
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _sweepable_files()
        if needle in path.read_text(errors="ignore")
    ]
    assert not offenders, (
        f"`{needle}` is not installable — {distribution} is not published to "
        f"PyPI. Document the local path install instead. Offenders: {offenders}"
    )


def test_framework_integrations_import_the_module_that_exists() -> None:
    """The importable module is `framework_integrations`, not `agent_middleware`.

    Every README under framework_integrations/ documented
    `from agent_middleware import ...`, which raises ModuleNotFoundError.
    """

    offenders = []
    for path in (REPO_ROOT / "framework_integrations").rglob("*"):
        if path.suffix not in {".md", ".py"}:
            continue
        for lineno, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if line.strip().startswith(("from agent_middleware", "import agent_middleware")):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert not offenders, (
        "there is no `agent_middleware` package; import `framework_integrations`. "
        f"Offenders: {offenders}"
    )


def test_gate_scripts_share_interpreter_resolution() -> None:
    """Gates must not resolve an interpreter by name alone.

    Selecting `python3.12` by existence (never trying `python3`) made both trust
    gates fail with `No module named pytest` on any machine where a bare system
    python3.12 is on PATH.
    """

    helper = REPO_ROOT / "scripts" / "lib" / "python_env.sh"
    assert helper.is_file(), "scripts/lib/python_env.sh is the shared resolver"

    for name in ("trust_coverage_gate.sh", "trust_release_gate.sh", "core_quality_gate.sh"):
        script = REPO_ROOT / "scripts" / name
        assert script.is_file(), f"scripts/{name} must exist"
        text = script.read_text()
        assert "lib/python_env.sh" in text, f"scripts/{name} must source the shared resolver"
        assert 'PYTHON_BIN="${PYTHON:-python3.12}"' not in text, (
            f"scripts/{name} reintroduced the hardcoded interpreter"
        )


def test_repo_guardian_only_invokes_scripts_that_exist() -> None:
    """`repo_guardian.py` counts failures, so a missing script fails every run."""

    text = (REPO_ROOT / "scripts" / "repo_guardian.py").read_text()
    referenced = set(re.findall(r'"(scripts/[\w./-]+\.(?:sh|py))"', text))
    missing = sorted(ref for ref in referenced if not (REPO_ROOT / ref).is_file())
    assert not missing, f"repo_guardian.py references scripts that do not exist: {missing}"


def test_production_env_template_is_production_like() -> None:
    """`.env.production` must set ENVIRONMENT.

    `Settings.ENVIRONMENT` defaults to "local", which
    `is_production_like_environment()` treats as NOT production-like — so
    omitting it silently disables every production trust guardrail.
    """

    from app.core.trust_mode import is_production_like_environment

    env_production = REPO_ROOT / ".env.production"
    assert env_production.is_file()

    values = {}
    for raw in env_production.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    assert "ENVIRONMENT" in values, ".env.production must set ENVIRONMENT explicitly"
    assert is_production_like_environment(values["ENVIRONMENT"]), (
        f"ENVIRONMENT={values['ENVIRONMENT']!r} is not production-like, so the "
        "production trust guardrails would not engage"
    )
