"""Guards the first five minutes of a new user's experience.

Each assertion here corresponds to a failure that a skeptic actually hit when
following the documented setup: copy `.env.example`, start the API, run the
gates. These are cheap to re-break in a docs edit, so they are pinned.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

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
    "openai-agent-middleware",
    "b2a-sdk",
)

#: Paths excluded from the docs sweep: vendored/marketing site content, and the
#: two files whose whole job is to record or assert these strings.
_DOC_SWEEP_EXCLUDES = (
    "site/",
    "node_modules/",
    # Gitignored agent scratch: `.claude/worktrees/` holds full checkouts, so a
    # sweep that walks it re-finds every excluded file under a second path and
    # fails on a copy of a file this list already forgave.
    ".claude/",
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
            if line.strip().startswith(
                ("from agent_middleware", "import agent_middleware")
            ):
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
    helper_text = helper.read_text()
    assert helper_text.index("elif command -v uv") < helper_text.index(
        "for _candidate in python3.12"
    ), "gates must prefer the requirements-resolved uv environment"

    for name in (
        "trust_coverage_gate.sh",
        "trust_release_gate.sh",
        "core_quality_gate.sh",
    ):
        script = REPO_ROOT / "scripts" / name
        assert script.is_file(), f"scripts/{name} must exist"
        text = script.read_text()
        assert "lib/python_env.sh" in text, (
            f"scripts/{name} must source the shared resolver"
        )
        assert 'PYTHON_BIN="${PYTHON:-python3.12}"' not in text, (
            f"scripts/{name} reintroduced the hardcoded interpreter"
        )


def test_repo_guardian_only_invokes_scripts_that_exist() -> None:
    """`repo_guardian.py` counts failures, so a missing script fails every run."""

    text = (REPO_ROOT / "scripts" / "repo_guardian.py").read_text()
    referenced = set(re.findall(r'"(scripts/[\w./-]+\.(?:sh|py))"', text))
    missing = sorted(ref for ref in referenced if not (REPO_ROOT / ref).is_file())
    assert not missing, (
        f"repo_guardian.py references scripts that do not exist: {missing}"
    )


def test_repo_does_not_ship_stale_production_config_paths() -> None:
    """Railway IaC plus the exact-SHA Dockerfile are the production owners.

    The retired files looked authoritative but could not satisfy the current
    production trust contract. Keep them absent and ignored so operators do
    not revive a second, unsafe source of production configuration.
    """

    retired = (
        ".env.production",
        "docker-compose.prod.yml",
        "railway.json",
        "railway.toml",
    )
    for name in retired:
        assert not (REPO_ROOT / name).exists(), f"retired artifact returned: {name}"
        ignore_check = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ignore_check.returncode == 0, f"retired artifact is not ignored: {name}"

    assert (REPO_ROOT / ".railway" / "railway.ts").is_file()

    deploy_sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    assert "does not ship `.env.production` or" in deploy_sop
    assert "`docker-compose.prod.yml`" in deploy_sop

    local_compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "Local development only" in local_compose
    assert "docs/deploy-railway.md" in local_compose
    assert "Production additions" not in local_compose
    assert "POSTGRES_PASSWORD: changeme" not in local_compose


def test_readme_version_badge_matches_changelog_release_state() -> None:
    """The front-page badge must not present an untagged version as released.

    It read `version-v1.3.0-blue` while CHANGELOG.md was still headed
    `[Unreleased] — planned v1.3.0` and no v1.3.0 tag existed. The source
    version (pyproject, APP_VERSION) legitimately runs ahead of the tag; the
    badge is what a reader takes as the shipped release.
    """

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    top = next(line for line in changelog.splitlines() if line.startswith("## "))
    readme = (REPO_ROOT / "README.md").read_text()
    badge = re.search(r"img\.shields\.io/badge/version-(.+?)-([0-9a-z]+)\)", readme)
    assert badge, "README.md must keep its version badge"
    # shields.io static badges escape a literal dash as `--`.
    message = badge.group(1).replace("--", "-")

    if top.startswith("## [Unreleased]"):
        assert "unreleased" in message.lower(), (
            f"CHANGELOG.md's newest section is {top!r}, but the README badge "
            f"says {message!r} as if that version had shipped"
        )
        planned = re.search(r"planned (v\d+\.\d+\.\d+)", top)
        if planned:
            assert message.startswith(planned.group(1)), (
                f"README badge {message!r} does not name the planned "
                f"{planned.group(1)} from CHANGELOG.md"
            )
    else:
        released = re.match(r"## \[(\d+\.\d+\.\d+)\]", top)
        assert released, f"unrecognized CHANGELOG.md heading: {top!r}"
        assert message == f"v{released.group(1)}", (
            f"README badge {message!r} does not match the newest released "
            f"CHANGELOG.md section {top!r}"
        )


# --- Runnable examples -----------------------------------------------------


def test_dry_run_example_uses_the_wallet_it_creates() -> None:
    """The example must bill against the server-assigned wallet id.

    It previously created a sponsor wallet and then billed `sponsor-0`, an id
    the server never issues, so every dry-run call returned
    `404 wallet_not_found` and the example died on its first scenario.
    """

    source = (REPO_ROOT / "examples" / "dry_run_example.py").read_text()
    assert "sponsor-0" not in source, (
        "wallet ids are server-assigned (e.g. spn-bde42b5c4606); a hardcoded id "
        "returns 404 wallet_not_found"
    )
    assert 'wallet["wallet_id"]' in source, (
        "the example must read the wallet id out of the creation response"
    )


def test_dry_run_example_states_its_proof_surface_prerequisite() -> None:
    """Dry-run endpoints are on the billing router, which is a proof surface."""

    source = (REPO_ROOT / "examples" / "dry_run_example.py").read_text()
    assert "ENABLE_PROOF_SURFACES=true" in source, (
        "without proof surfaces enabled the billing router is not mounted and "
        "every dry-run call 404s; the example must say so"
    )


def test_dry_run_example_points_at_quickstart() -> None:
    """Nobody should demo cost estimation as metering.

    The dry-run script is a legacy billing simulation. Its header must route
    prospects to the supported trust loop in docs/quickstart.md first.
    """

    source = (REPO_ROOT / "examples" / "dry_run_example.py").read_text()
    assert "docs/quickstart.md" in source, (
        "the dry-run header must point readers at docs/quickstart.md, the "
        "supported trust loop, instead of presenting simulation as metering"
    )


def test_mcp_example_offers_show_manifest_for_local_display() -> None:
    """`--register` printed metadata but registered nothing with the backend.

    The example now offers `--show-manifest` as the honest name for the
    local-only display step. `--register` stays as a deprecated alias so old
    commands keep working.
    """

    source = (REPO_ROOT / "examples" / "mcp_tool_example.py").read_text()
    assert "--show-manifest" in source, (
        "the example must offer --show-manifest, a name that does not imply "
        "backend registration"
    )
    assert "--register" in source, (
        "--register must stay as a deprecated alias; removing it would break "
        "documented commands without warning"
    )
    assert "deprecat" in source.lower(), (
        "the --register alias must be labeled deprecated so prospects stop "
        "trusting it as a real registration step"
    )


def test_mcp_example_discloses_no_backend_registration() -> None:
    """The register step must say plainly that it never contacts the backend."""

    source = (REPO_ROOT / "examples" / "mcp_tool_example.py").read_text()
    assert "does not register" in source or "no backend" in source.lower(), (
        "the example must state it does not register anything with the "
        "backend; a no-op register step burns trust in front of an engineer"
    )
    assert "quickstart" in source.lower(), (
        "the example must route readers to the supported governed loop "
        "(docs/quickstart.md or the partner runbook), not the standalone flow"
    )


def test_examples_readme_labels_mcp_register_local_only() -> None:
    """The examples README must not present `--register` as backend registration."""

    readme = (REPO_ROOT / "examples" / "README.md").read_text()
    assert "--show-manifest" in readme, (
        "the README must document --show-manifest as the honest flag name"
    )
    mcp_section = readme.split("mcp_tool_example.py", 1)[1]
    assert "local-only" in mcp_section or "local only" in mcp_section, (
        "the README's MCP section must say the display step is local-only "
        "and registers nothing with the backend"
    )


def test_partner_guide_positioning_avoids_exactly_once() -> None:
    """Approved sales language must match the engineering talk track.

    The positioning list offered "Exactly-once gateway authorization, debit,
    and receipt finalization" while the same file warns that a remote tool's
    side effect cannot be promised as exactly once. The retry story is: the
    same accepted key returns the same receipt, a new key is a new operation.
    """

    guide = (REPO_ROOT / "DESIGN_PARTNER_GUIDE.md").read_text()
    assert "Exactly-once gateway" not in guide, (
        "approved positioning must not promise an exactly-once gateway; the "
        "scoped promise is one accepted key, at most one debit"
    )


def test_demo_script_crowns_quickstart_over_manual_setup() -> None:
    """Prospects should meet one entry point, not two competing doors.

    The manual uvicorn-plus-env-exports block stays for the persistent-DB
    narrated demo, but the script must name `make quickstart` plus
    docs/quickstart.md as the preferred first step.
    """

    demo = (REPO_ROOT / "DEMO_SCRIPT.md").read_text()
    assert "make quickstart" in demo, "the demo script must crown make quickstart"
    assert "docs/quickstart.md" in demo, (
        "the demo script must point at docs/quickstart.md as the entry point"
    )
    lowered = demo.lower()
    assert "prefer" in lowered or "appendix" in lowered, (
        "the manual env-export block must be marked as the fallback, with "
        "quickstart named as the preferred entry"
    )


# --- Framework wrapper SDK floor --------------------------------------------

#: First b2a-sdk release with the typed async `AgentMiddlewareClient` trust
#: loop (`create_permit` / `invoke_tool` with caller-owned idempotency keys)
#: that every framework wrapper subclasses and calls (b2a_sdk/CHANGELOG.md).
B2A_SDK_TRUST_LOOP_FLOOR = Version("0.4.0")


def test_wrappers_require_an_sdk_that_ships_the_trust_loop() -> None:
    """A wrapper's `b2a-sdk` lower bound must exclude SDKs it cannot run on.

    The wrappers declared `b2a-sdk>=0.3.0`, so a resolver could pick a 0.3.x
    SDK that has no `AgentMiddlewareClient` and every governed call failed.
    The wrapper CI job installs the in-tree SDK, so nothing else exercises
    the declared floor.
    """

    sdk_version = Version(
        tomllib.loads((REPO_ROOT / "b2a_sdk" / "pyproject.toml").read_text())[
            "project"
        ]["version"]
    )
    pyprojects = sorted((REPO_ROOT / "wrappers").glob("*/pyproject.toml"))
    assert pyprojects, "expected framework wrappers under wrappers/"

    offenders = []
    for pyproject in pyprojects:
        rel = pyproject.relative_to(REPO_ROOT).as_posix()
        dependencies = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
        sdk_requirements = [
            requirement
            for requirement in map(Requirement, dependencies)
            if canonicalize_name(requirement.name) == "b2a-sdk"
        ]
        if len(sdk_requirements) != 1:
            offenders.append(f"{rel}: expected one b2a-sdk dependency")
            continue
        specifier = sdk_requirements[0].specifier
        floors = [Version(spec.version) for spec in specifier if spec.operator == ">="]
        if not floors or max(floors) < B2A_SDK_TRUST_LOOP_FLOOR:
            offenders.append(f"{rel}: b2a-sdk{specifier} admits a pre-trust-loop SDK")
        if not specifier.contains(sdk_version):
            offenders.append(
                f"{rel}: b2a-sdk{specifier} excludes in-tree {sdk_version}"
            )
    assert not offenders, (
        f"wrappers must require b2a-sdk>={B2A_SDK_TRUST_LOOP_FLOOR}: {offenders}"
    )


# --- Deployment posture is auditable ---------------------------------------


@pytest.mark.anyio
async def test_health_payload_exposes_guardrail_posture() -> None:
    """`ENVIRONMENT` decides whether production guardrails engage.

    It defaults to "local", so a deploy that never sets it runs unguarded. The
    resolved value must be observable without reading the host's secret store.
    """

    from app.core.health import gather_dependency_report

    report = await gather_dependency_report()

    assert "environment" in report, "health must report the resolved ENVIRONMENT"
    assert "production_like" in report, (
        "health must report whether production trust guardrails engage"
    )
    assert isinstance(report["production_like"], bool)

    from app.core.config import get_settings
    from app.core.trust_mode import is_production_like_environment

    settings = get_settings()
    assert report["environment"] == settings.ENVIRONMENT
    assert report["production_like"] is is_production_like_environment(
        settings.ENVIRONMENT
    )


# --- Operator docs quote what the code does --------------------------------

_ERROR_HEADING = re.compile(r"^### `([A-Za-z_][\w.]*Error): (.+)`$", re.MULTILINE)
# Raised by Python or third-party tooling, not by this codebase.
_EXTERNAL_ERRORS = frozenset({"ModuleNotFoundError", "alembic.util.exc.CommandError"})


def _app_source_with_joined_literals() -> str:
    """All of app/, with adjacent string literals joined across line breaks."""

    source = "\n".join(
        path.read_text() for path in sorted((REPO_ROOT / "app").rglob("*.py"))
    )
    return re.sub(r'"\s*\n\s*"', "", source)


def test_troubleshooting_error_headings_match_raised_errors() -> None:
    """Each `XxxError: message` heading must be an error the app raises.

    The headings once quoted a `ValueError` and a `RuntimeError` text that no
    code raised, so an operator searching for their traceback found nothing.
    """

    doc = (REPO_ROOT / "TROUBLESHOOTING.md").read_text()
    app_errors = [
        (name, message)
        for name, message in _ERROR_HEADING.findall(doc)
        if name not in _EXTERNAL_ERRORS
    ]
    assert app_errors, "expected startup-error headings in TROUBLESHOOTING.md"
    source = _app_source_with_joined_literals()
    for name, message in app_errors:
        assert re.search(rf"^class {re.escape(name)}\(", source, re.MULTILINE), (
            f"TROUBLESHOOTING.md names {name}, which app/ does not define"
        )
        assert message in source, (
            f"TROUBLESHOOTING.md quotes `{name}: {message}`, which app/ never raises"
        )


def test_server_json_does_not_advertise_the_disabled_standard_mcp_remote() -> None:
    """No registry remote while the production SOP keeps `POST /mcp` off.

    With ENABLE_STANDARD_MCP_ENDPOINT forbidden on the first-party origin,
    `/mcp` answers 404 there, so a `remotes` entry would advertise a transport
    the server does not serve. Adding one means changing the SOP first
    (docs/mcp-registry-submission.md, "Publish gate"), then this test.
    """

    deploy_sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    sop_row = next(
        line
        for line in deploy_sop.splitlines()
        if line.startswith("| `ENABLE_STANDARD_MCP_ENDPOINT` |")
    )
    assert "Do not turn this on" in sop_row
    manifest = json.loads((REPO_ROOT / "server.json").read_text())
    assert not manifest.get("remotes"), (
        "server.json declares a remote the production SOP keeps disabled"
    )
    submission = (REPO_ROOT / "docs" / "mcp-registry-submission.md").read_text()
    assert "deploy-railway.md#required-production-variables" in submission
