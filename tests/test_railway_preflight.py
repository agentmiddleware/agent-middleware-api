"""Deploy-gate coverage for scripts/railway_preflight.py.

The preflight only earns its place if it fails on the states that actually
break a Railway deploy: a tree ahead of the deployed schema, a database
bootstrapped by ``create_all`` and never stamped, a service that came up
with memory state or proof surfaces on, and a production service whose tool
catalogs are readable without credentials.
"""

import asyncio
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_preflight():
    spec = importlib.util.spec_from_file_location(
        "railway_preflight", REPO_ROOT / "scripts" / "railway_preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_preflight()


@pytest.fixture(autouse=True)
def clean_release_checkout(monkeypatch):
    """Manifest tests run in a shared worktree containing intended edits."""
    monkeypatch.setattr(preflight, "_tree_is_clean", lambda: True)


@pytest.fixture
def migrated_db(tmp_path, monkeypatch):
    """A sqlite DB upgraded to head, plus its async URL."""
    db_path = tmp_path / "preflight.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", async_url)
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.set_event_loop(asyncio.new_event_loop())
    return async_url, f"sqlite:///{db_path}"


def test_tree_head_is_single():
    """Two heads means someone branched migrations — deploys would be ambiguous."""
    assert preflight._tree_head()


def test_tree_is_clean_reports_git_status(monkeypatch):
    """The real clean-checkout gate answers from git, both directions.

    The autouse fixture forces _tree_is_clean True for the manifest suite, so
    without this test the real function could return True unconditionally (or
    raise) and nothing would go red. A fresh module copy bypasses that patch.
    """
    from types import SimpleNamespace

    fresh = _load_preflight()

    def fake_run(stdout, **kwargs):
        assert kwargs.get("cwd") == REPO_ROOT
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: fake_run("", **kwargs)
    )
    assert fresh._tree_is_clean() is True

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: fake_run(
            " M tests/test_railway_preflight.py\n", **kwargs
        ),
    )
    assert fresh._tree_is_clean() is False


def test_passes_when_schema_at_head(migrated_db):
    async_url, _ = migrated_db
    assert preflight.check_db(async_url) is True


def test_fails_on_empty_database(tmp_path):
    assert preflight.check_db(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}") is False


def test_fails_when_database_behind_tree(migrated_db):
    async_url, sync_url = migrated_db
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE alembic_version SET version_num = '021_ledger_stripe_event_id'"
            )
        )
    engine.dispose()

    assert preflight.check_db(async_url) is False


def test_fails_on_unstamped_create_all_bootstrap(migrated_db, capsys):
    """Table presence cannot establish schema or data-migration equivalence."""
    async_url, sync_url = migrated_db
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    assert preflight.check_db(async_url) is False
    output = capsys.readouterr().out
    assert "manual review" in output
    assert "schema and data-migration history" in output
    assert "proven matching historical revision" in output
    assert "Run `alembic stamp head`" not in output


def test_public_db_mode_fails_closed_without_public_url(
    monkeypatch,
    capsys,
):
    private_secret = "postgresql://user:private-secret@postgres.railway.internal/db"
    monkeypatch.setenv("DATABASE_URL", private_secret)
    monkeypatch.delenv("DATABASE_PUBLIC_URL", raising=False)

    assert preflight.main(["--db", "--public-db", "--strict"]) == 1

    output = capsys.readouterr().out
    assert "DATABASE_PUBLIC_URL is required" in output
    assert private_secret not in output
    assert "private-secret" not in output


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@postgres.railway.internal/db",
        "postgresql://user:secret@127.0.0.1:5432/db",
        "sqlite+aiosqlite:///local.db",
    ],
)
def test_public_db_mode_rejects_private_or_non_postgres_urls(
    monkeypatch,
    capsys,
    url,
):
    monkeypatch.setenv("DATABASE_PUBLIC_URL", url)

    assert preflight.main(["--db", "--public-db", "--strict"]) == 1

    output = capsys.readouterr().out
    assert "[preflight] FAIL" in output
    assert url not in output
    assert "secret" not in output


def test_public_db_mode_uses_only_explicit_value_without_rendering_it(
    monkeypatch,
    capsys,
):
    public_url = "postgresql://user:public-secret@switchback.proxy.rlwy.net:5432/db"
    seen = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://wrong:private@internal/db")
    monkeypatch.setenv("DATABASE_PUBLIC_URL", public_url)
    monkeypatch.setattr(
        preflight,
        "check_db",
        lambda url: seen.append(url) is None,
    )

    assert preflight.main(["--db", "--public-db", "--strict"]) == 0
    assert seen == [public_url]
    assert public_url not in capsys.readouterr().out


def test_public_db_connection_failure_does_not_render_url(
    monkeypatch,
    capsys,
):
    public_url = "postgresql://user:public-secret@switchback.proxy.rlwy.net:5432/db"
    monkeypatch.setenv("DATABASE_PUBLIC_URL", public_url)

    def fail(_url):
        raise RuntimeError(f"could not connect to {public_url}")

    monkeypatch.setattr(preflight, "check_db", fail)

    assert preflight.main(["--db", "--public-db", "--strict"]) == 1
    output = capsys.readouterr().out
    assert "connection or schema check failed" in output
    assert public_url not in output
    assert "public-secret" not in output


def test_release_workflow_validates_without_production_mutation() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "railway-deploy.yml").read_text()

    resolve = workflow.index("- name: Resolve release identity")
    ci_gate = workflow.index("- name: Require green CI for exact commit")
    posture = workflow.index("- name: Preflight — current production posture")
    clean = workflow.index("- name: Confirm source checkout is clean")
    summary = workflow.index("- name: Manual private release required")
    assert resolve < ci_gate < posture < clean < summary
    assert "deployment performed: **no**" in workflow
    # A --live-only run cannot observe the dogfood posture, so the summary must
    # not report it as checked.
    assert (
        "current production posture: public posture passed; dogfood posture is "
        "private and verified in-container by the operator SOP"
    ) in workflow
    assert "current production posture: passed" not in workflow
    assert 'git merge-base --is-ancestor "$sha" origin/main' in workflow
    assert 'select(.event == "push"' in workflow
    assert "scripts/railway_preflight.py --live --strict" in workflow
    assert "railway up" not in workflow
    assert "railway variable set" not in workflow
    assert "railway run --service Postgres --environment production" not in workflow
    assert "--public-db" not in workflow
    assert "DATABASE_PUBLIC_URL" not in workflow
    assert "RAILWAY_TOKEN" not in workflow
    assert "skip_ci_gate" not in workflow


def test_private_pilot_sop_runs_schema_check_inside_api_container() -> None:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    private_release = sop[
        sop.index("### Private operator release") : sop.index(
            "### Customer operations manifest"
        )
    ]

    assert "uuid.uuid4().hex" in sop
    assert 'RELEASE_MARKER="manual-exact-sha-$DEPLOY_SHA-$RELEASE_NONCE"' in sop
    assert "select(.meta.cliMessage == $marker)" in sop
    assert 'PROJECT_ID="$(jq -er \'.railway_project_id\' "$MANIFEST")"' in sop
    assert 'ENVIRONMENT="$(jq -er \'.environment\' "$MANIFEST")"' in sop
    assert 'API_URL="$(jq -er \'.public_url\' "$MANIFEST")"' in sop
    assert "select(.name == $environment)" in sop
    assert sop.count('--project "$PROJECT_ID"') >= 7
    assert '--deployment-instance "$INSTANCE_ID"' in sop
    assert "python scripts/retire_owner_keys.py --private-db" in sop
    assert "python scripts/railway_preflight.py --db --runtime-posture --strict" in sop
    # Schema parity alone no longer covers the dogfood posture. The only place
    # --db --strict may appear is the rollback form for images without
    # --runtime-posture, and there the inline check must run before the
    # sentinel in the same SSH call.
    schema_only = "python scripts/railway_preflight.py --db --strict"
    paired = f'{schema_only} && python -c "$1" && printf "PRIVATE_RELEASE_CHECKS_OK'
    assert sop.count(schema_only) == sop.count(paired) == 1
    assert "PRIVATE_RELEASE_CHECKS_OK" in sop
    assert 'test "$sentinel_count" -eq 1' in sop
    assert 'test "$post_ready" = "true"' in sop
    assert sop.count('--manifest "$MANIFEST" --url "$API_URL"') == 2
    assert (
        'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"'
        in private_release
    )
    assert 'railway up "$RELEASE_CONTEXT" --path-as-root' in private_release
    assert (
        'test "$(cat "$RELEASE_CONTEXT/.build_commit_sha")" = "$DEPLOY_SHA"'
        in private_release
    )
    assert "railway variable set COMMIT_SHA" not in private_release
    assert "--build-arg COMMIT_SHA" not in private_release
    source_gate = private_release.index(
        "python3 scripts/railway_preflight.py --manifest-only"
    )
    current_gate = private_release.index(
        'python3 scripts/railway_preflight.py --live --strict --url "$API_URL"'
    )
    release_context = private_release.index(
        'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"'
    )
    deploy = private_release.index('railway up "$RELEASE_CONTEXT" --path-as-root')
    private_deploy = private_release[
        deploy : private_release.index(
            "# Resolve and wait for the uniquely marked deployment"
        )
    ]
    assert "--no-gitignore" in private_deploy
    post_gate = private_release.rindex(
        "python3 scripts/railway_preflight.py --live --strict"
    )
    current_private = private_release.index(
        '--deployment-instance "$CURRENT_INSTANCE_ID"'
    )
    assert (
        source_gate
        < current_gate
        < current_private
        < release_context
        < deploy
        < post_gate
    )
    assert "`railway run` executes locally" in sop
    assert "a `--live`-only run does not verify the dogfood posture" in sop


def test_verification_checklist_pairs_public_gate_with_private_posture() -> None:
    """Step 5's --live gate is public-only; the step must say so and give the
    in-container command that verifies the dogfood posture."""
    checklist = (
        REPO_ROOT / "docs" / "deployment-verification-checklist.md"
    ).read_text()
    step5 = checklist[
        checklist.index("5. **Run the strict live preflight**") : checklist.index(
            "6. **List what is still not live.**"
        )
    ]

    assert "python3 scripts/railway_preflight.py --live --strict" in step5
    assert "public-only" in step5
    assert '--deployment-instance "$INSTANCE_ID"' in step5
    assert (
        "python scripts/railway_preflight.py --db --runtime-posture --strict" in step5
    )
    assert "#rolling-back-to-an-image-without---runtime-posture" in step5


def _private_release_sop() -> str:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    return sop[
        sop.index("### Private operator release") : sop.index(
            "### Customer operations manifest"
        )
    ]


def _documented_runtime_posture_check() -> str:
    """The inline check the SOP defines for images without --runtime-posture."""
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    definitions = re.findall(r"^RUNTIME_POSTURE_CHECK='([^']*)'$", sop, re.MULTILINE)
    assert len(definitions) == 1
    return definitions[0]


def test_private_release_checks_current_instance_posture_before_deploying() -> None:
    """The public gate cannot see the dogfood posture, so the SOP checks the
    instance serving traffic privately before anything changes."""
    private_release = _private_release_sop()

    definition = private_release.index("RUNTIME_POSTURE_CHECK='import os, sys")
    current_live = private_release.index(
        'python3 scripts/railway_preflight.py --live --strict --url "$API_URL"'
    )
    current_private = private_release.index(
        '--deployment-instance "$CURRENT_INSTANCE_ID"'
    )
    stop_gate = private_release.index('echo "blocked: migration 037')
    deploy = private_release.index('railway up "$RELEASE_CONTEXT" --path-as-root')
    assert current_live < definition < current_private < stop_gate < deploy

    current_check = private_release[current_private:stop_gate]
    assert (
        r"""sh -c 'python -c "$1" && printf "CURRENT_RUNTIME_POSTURE_OK\\n"' """
        r'sh "$RUNTIME_POSTURE_CHECK")"'
    ) in current_check
    assert "grep -c '^CURRENT_RUNTIME_POSTURE_OK$'" in current_check
    assert 'test "$current_count" -eq 1' in current_check
    # Exactly one running instance, or the check refuses to pick one.
    assert 'error("expected exactly one running API instance")' in private_release


def test_rollback_to_image_without_runtime_posture_keeps_private_posture() -> None:
    """An older image rejects --runtime-posture (argparse exit 2). The rollback
    form must still run the scrub, schema parity, and the inline posture check
    before the sentinel, pinned to the new instance."""
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    rollback_paragraph = sop.index(
        "Roll back by deploying the previously green exact SHA"
    )
    note = sop.index("#### Rolling back to an image without `--runtime-posture`")
    assert rollback_paragraph < note < sop.index("### Customer operations manifest")
    rollback = sop[note : sop.index("### Customer operations manifest")]

    assert "`8c95229`" in rollback
    assert '--deployment-instance "$INSTANCE_ID"' in rollback
    assert (
        "sh -c 'python scripts/retire_owner_keys.py --private-db && "
        "python scripts/railway_preflight.py --db --strict && "
        r"""python -c "$1" && printf "PRIVATE_RELEASE_CHECKS_OK\\n"' """
        r'sh "$RUNTIME_POSTURE_CHECK")"'
    ) in rollback
    # The SOP's post-deploy command points to the rollback form.
    assert (
        'use the form in "Rolling back to an image without\n# --runtime-posture"'
        in _private_release_sop()
    )


def test_rollback_live_gates_verify_the_signing_key_from_a_gate_checkout() -> None:
    """A rollback to a release whose own preflight predates the locked
    catalogs runs the live gates from a gate checkout. The signing key is
    still checked by the tool, from the manifest, not by hand."""
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    rollback = sop[
        sop.index(
            "#### Rolling back to an image without `--runtime-posture`"
        ) : sop.index("### Customer operations manifest")
    ]

    assert 'GATE_SHA="$(git rev-parse origin/main)"' in rollback
    assert 'git archive "$GATE_SHA" | tar -x -C "$GATE_DIR"' in rollback
    assert (
        "grep -q -- '--expected-signing-key-id' "
        '"$GATE_DIR/scripts/railway_preflight.py"'
    ) in rollback
    assert '''SIGNING_KEY_ID="$(jq -er '.signing_key_id' "$MANIFEST")"''' in rollback
    assert (
        """SIGNING_PUBLIC_KEY_SHA256="$(jq -er '.signing_public_key_sha256' """
        '''"$MANIFEST")"'''
    ) in rollback
    # The jq fields are the manifest's own field names.
    for field in re.findall(r"jq -er '\.([a-z0-9_]+)' \"\$MANIFEST\"", rollback):
        assert field in preflight._MANIFEST_FIELDS
    pre_deploy = (
        'python3 "$GATE_DIR/scripts/railway_preflight.py" --live --strict '
        '--url "$API_URL"\n'
    )
    post_deploy = (
        'python3 "$GATE_DIR/scripts/railway_preflight.py" --live --strict '
        '--url "$API_URL" \\\n'
        '  --expected-version "$EXPECTED_VERSION" '
        '--expected-commit-sha "$DEPLOY_SHA" \\\n'
        '  --expected-signing-key-id "$SIGNING_KEY_ID" \\\n'
        '  --expected-signing-public-key-sha256 "$SIGNING_PUBLIC_KEY_SHA256"\n'
    )
    assert pre_deploy in rollback
    assert post_deploy in rollback
    assert rollback.index(pre_deploy) < rollback.index(post_deploy)
    assert "separately" not in rollback


def _railway_cli_version_guard() -> str:
    guards = re.findall(
        r"^railway --version \| python3 -c '[^\n]*'$",
        _private_release_sop(),
        re.MULTILINE,
    )
    assert len(guards) == 1
    return guards[0]


def test_private_release_stops_on_an_old_railway_cli_before_using_it() -> None:
    """The guard is the first Railway CLI call in the operator script."""
    private_release = _private_release_sop()
    script = private_release[private_release.index("set -euo pipefail") :]
    first_railway_call = re.search(r"(?m)(^|\$\()railway ", script)

    assert first_railway_call is not None
    assert script.index(_railway_cli_version_guard()) == first_railway_call.start()


@pytest.mark.parametrize(
    ("version_output", "exit_status", "allowed"),
    [
        ("railway 5.43.0", 0, True),
        ("railway 5.62.1", 0, True),
        ("railway 6.0.0", 0, True),
        ("railway 5.42.9", 0, False),
        ("railway 4.99.99", 0, False),
        ("railway dev", 0, False),
        ("railway 5.62.1", 1, False),
        (None, 0, False),
    ],
    ids=[
        "5.43.0",
        "5.62.1",
        "6.0.0",
        "5.42.9",
        "4.99.99",
        "unparseable",
        "cli_error",
        "no_cli",
    ],
)
def test_railway_cli_version_guard_fails_closed(
    tmp_path,
    version_output,
    exit_status,
    allowed,
) -> None:
    """Run the SOP's guard line under set -euo pipefail with a stand-in CLI."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("needs bash")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if version_output is not None:
        railway = bin_dir / "railway"
        railway.write_text(f'#!/bin/sh\necho "{version_output}"\nexit {exit_status}\n')
        railway.chmod(0o755)
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "python3").symlink_to(sys.executable)
    script = f"set -euo pipefail\n{_railway_cli_version_guard()}\necho reached\n"
    result = subprocess.run(
        [bash, "-c", script],
        env={"PATH": f"{bin_dir}:{python_dir}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert (result.returncode == 0) is allowed, result.stderr
    assert ("reached" in result.stdout) is allowed


def _rollback_section() -> str:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    return sop[
        sop.index(
            "#### Rolling back to an image without `--runtime-posture`"
        ) : sop.index("### Customer operations manifest")
    ]


def test_signing_key_check_documents_what_it_does_not_prove() -> None:
    """The check proves publication, not the key the process signs with; the
    script and the rollback section both say so, with the rotation steps."""
    rollback = _rollback_section()
    docstring = preflight.__doc__

    for described in (rollback, " ".join(docstring.split())):
        assert "GET /v1/signing-keys/active" in described
        assert "SigningKeyService.ensure_active_key" in described
        assert "POST /v1/admin/signing-keys/rotate" in described
    assert "not that the process\n*signs* with it" in rollback
    assert "not that the process *signs* with it" in " ".join(docstring.split())
    assert "Retire the old key's metadata" in rollback
    assert "treat the signing-key check as unverified until it is done" in rollback


def test_signing_key_limitation_claims_match_the_code() -> None:
    """Pin the facts the limitation text relies on, so the text goes stale
    loudly: no rotation route exists, the active-key route needs credentials,
    and the public signing_key entry names no key."""
    app_sources = [path.read_text() for path in (REPO_ROOT / "app").rglob("*.py")]
    assert not any("signing-keys/rotate" in source for source in app_sources)

    keys_router = (REPO_ROOT / "app" / "routers" / "keys.py").read_text()
    active = keys_router[keys_router.index('@router.get("/active"') :]
    active = active[: active.index("@router.get(", 1)]
    assert "Depends(get_auth_context)" in active

    health = (REPO_ROOT / "app" / "core" / "health.py").read_text()
    check = health[health.index("async def _check_signing_key") :]
    check = check[: check.index("\nasync def ", 1)]
    assert "key_id" not in check
    assert '"loaded"' in check


def _first_party_block() -> str:
    blocks = re.findall(r"```bash\n(.*?)```", _rollback_section(), re.S)
    first_party = [block for block in blocks if "FIRST_PARTY_PROJECT_ID" in block]
    assert len(first_party) == 1
    return first_party[0]


def test_first_party_rollback_variant_replaces_every_manifest_input() -> None:
    rollback = _rollback_section()
    variant = rollback[
        rollback.index("##### First-party stack without a customer manifest") :
    ]
    block = _first_party_block()

    # The manifest-derived variables all have a named, non-live source.
    assert 'API_URL="https://api.thisisatest.tech"' in block
    assert 'ENVIRONMENT="production"' in block
    assert 'PROJECT_ID="${FIRST_PARTY_PROJECT_ID:?' in block
    assert 'SIGNING_KEY_ID="${FIRST_PARTY_SIGNING_KEY_ID:?' in block
    assert (
        'SIGNING_PUBLIC_KEY_SHA256="${FIRST_PARTY_SIGNING_PUBLIC_KEY_SHA256:?' in block
    )
    assert "first-party operations record" in block
    assert "first-party key-generation record" in block
    assert "stop and escalate" in block
    assert "MANIFEST" not in block
    # The steps it replaces or skips are named.
    assert "Replace the `MANIFEST=` line and the three `jq` assignments" in variant
    assert "Skip the `--manifest-only` step" in variant
    assert "drop the two `SIGNING_*` lines" in variant
    assert "If no\nfingerprint was ever recorded, stop and escalate." in variant
    assert "Never copy it from\n`/.well-known/trust-keys.json`" in variant


def _run_first_party_block(**environment):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("needs bash")
    script = (
        "set -euo pipefail\n"
        + _first_party_block()
        + 'printf "%s|%s|%s|%s|%s\\n" "$API_URL" "$ENVIRONMENT" "$PROJECT_ID" '
        + '"$SIGNING_KEY_ID" "$SIGNING_PUBLIC_KEY_SHA256"\n'
    )
    return subprocess.run(
        [bash, "-c", script],
        env={"PATH": os.environ.get("PATH", ""), **environment},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


_FIRST_PARTY_RECORDS = {
    "FIRST_PARTY_PROJECT_ID": "123e4567-e89b-42d3-a456-426614174000",
    "FIRST_PARTY_SIGNING_KEY_ID": "first-party-production-ed25519-v2",
    "FIRST_PARTY_SIGNING_PUBLIC_KEY_SHA256": "ab" * 32,
}


def test_first_party_rollback_variant_sets_the_gate_inputs() -> None:
    result = _run_first_party_block(**_FIRST_PARTY_RECORDS)

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "https://api.thisisatest.tech|production|"
        + "|".join(_FIRST_PARTY_RECORDS.values())
        + "\n"
    )


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("FIRST_PARTY_SIGNING_PUBLIC_KEY_SHA256", "stop and escalate"),
        ("FIRST_PARTY_SIGNING_KEY_ID", "first-party key-generation record"),
        ("FIRST_PARTY_PROJECT_ID", "first-party operations record"),
    ],
)
def test_first_party_rollback_variant_stops_without_a_record(missing, message) -> None:
    records = {k: v for k, v in _FIRST_PARTY_RECORDS.items() if k != missing}
    result = _run_first_party_block(**records)

    assert result.returncode != 0
    assert result.stdout == ""
    assert message in result.stderr


def _ssh_assignments() -> list[tuple[str, str]]:
    """Every `<name>_output="$(railway ssh ...)"` block in the SOP."""
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    return re.findall(
        r'^((\w+_output)="\$\(railway ssh \\\n.*?\)" \\\n  \|\| \{[^\n]*\})$',
        sop,
        re.MULTILINE | re.DOTALL,
    )


def test_every_ssh_check_prints_its_output_before_failing() -> None:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    assignments = _ssh_assignments()

    assert sop.count('_output="$(railway ssh') == len(assignments) == 3
    for block, name in assignments:
        assert block.endswith(f"|| {{ printf '%s\\n' \"${name}\"; exit 1; }}")


@pytest.mark.parametrize(
    ("ssh_output", "ssh_status", "passes"),
    [
        ("[preflight] PASS runtime posture\nSENTINEL", 0, True),
        ("[preflight] FAIL runtime posture: no Railway runtime marker", 1, False),
        ("[preflight] FAIL runtime posture", 1, False),
    ],
    ids=["check_passes", "check_fails_with_reason", "check_fails"],
)
@pytest.mark.parametrize("which", ["current_output", "remote_output"])
def test_failed_ssh_check_output_reaches_the_operator(
    tmp_path,
    ssh_output,
    ssh_status,
    passes,
    which,
) -> None:
    """Under set -euo pipefail the SOP block must still show why the private
    check failed, and must still stop."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("needs bash")
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    counter = "current_count" if which == "current_output" else "sentinel_count"
    sentinel = (
        "CURRENT_RUNTIME_POSTURE_OK"
        if which == "current_output"
        else "PRIVATE_RELEASE_CHECKS_OK"
    )
    block = re.search(
        rf'^{which}="\$\(railway ssh \\\n.*?^test "\${counter}" -eq 1$',
        sop,
        re.MULTILINE | re.DOTALL,
    ).group(0)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    railway = bin_dir / "railway"
    railway.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"{ssh_output.replace('SENTINEL', sentinel)}\"\n"
        f"exit {ssh_status}\n"
    )
    railway.chmod(0o755)
    # The variables the SOP sets before these blocks.
    context = (
        "PROJECT_ID=p SERVICE=api-service ENVIRONMENT=production "
        "INSTANCE_ID=i CURRENT_INSTANCE_ID=i RUNTIME_POSTURE_CHECK=check\n"
    )
    script = f"set -euo pipefail\n{context}{block}\necho REACHED_AFTER_CHECK\n"
    result = subprocess.run(
        [bash, "-c", script],
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    first_line = ssh_output.splitlines()[0]
    assert first_line in result.stdout
    assert (result.returncode == 0) is passes
    assert ("REACHED_AFTER_CHECK" in result.stdout) is passes


def _run_documented_runtime_posture_check(tmp_path, *, dotenv_in=None, **environment):
    """Run the SOP's inline check the way the container does.

    The service root is a directory whose ``app`` package links to this
    tree's, so the snippet locates the service's working directory from
    ``app.__file__`` exactly as it does at ``/app``. The check itself runs
    from a separate empty directory. A minimal environment keeps the test
    runner's variables out.
    """
    service = tmp_path / "service"
    cwd = tmp_path / "cwd"
    service.mkdir()
    cwd.mkdir()
    (service / "app").symlink_to(REPO_ROOT / "app", target_is_directory=True)
    if dotenv_in is not None:
        (tmp_path / dotenv_in / ".env").write_text("ENABLE_DOGFOOD_TOOL=false\n")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(service)}
    env.update(environment)
    return subprocess.run(
        [sys.executable, "-c", _documented_runtime_posture_check()],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


# What a deployed Railway container carries besides the service's variables.
_RAILWAY_MARKER = {"RAILWAY_SERVICE_ID": "0f0e0d0c-api-service"}


def test_documented_runtime_posture_check_passes_in_production(tmp_path) -> None:
    result = _run_documented_runtime_posture_check(
        tmp_path,
        ENVIRONMENT="production",
        ENABLE_DOGFOOD_TOOL="false",
        ENABLE_DOGFOOD_SECOND_TOOL="false",
        **_RAILWAY_MARKER,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "[preflight] PASS runtime posture\n"


def test_documented_runtime_posture_check_matches_the_flag() -> None:
    """The inline check carries the same guards as --runtime-posture."""
    snippet = _documented_runtime_posture_check()

    assert "HOSTED_RUNTIME_MARKER_VARS" in snippet
    assert 'Path(".env")' in snippet
    assert 'Path(os.path.abspath(app.__file__)).parents[1] / ".env"' in snippet
    assert "except Exception as exc:" in snippet
    assert "type(exc).__name__" in snippet


@pytest.mark.parametrize(
    "environment",
    [
        {"ENVIRONMENT": "production", "ENABLE_DOGFOOD_TOOL": "true"},
        {"ENVIRONMENT": "production", "ENABLE_DOGFOOD_SECOND_TOOL": "true"},
        {"ENVIRONMENT": "local"},
        {},
    ],
    ids=["dogfood_tool", "dogfood_second_tool", "local", "environment_unset"],
)
def test_documented_runtime_posture_check_fails_closed(tmp_path, environment) -> None:
    result = _run_documented_runtime_posture_check(
        tmp_path, **_RAILWAY_MARKER, **environment
    )

    assert result.returncode == 1
    assert result.stdout == "[preflight] FAIL runtime posture\n"


@pytest.mark.parametrize(
    "marker_value", [None, "", "   "], ids=["unset", "empty", "blank"]
)
def test_documented_runtime_posture_check_requires_railway_marker(
    tmp_path,
    marker_value,
) -> None:
    environment = {"ENVIRONMENT": "production"}
    if marker_value is not None:
        environment["RAILWAY_SERVICE_ID"] = marker_value
    result = _run_documented_runtime_posture_check(tmp_path, **environment)

    assert result.returncode == 1
    assert result.stdout == (
        "[preflight] FAIL runtime posture: no Railway runtime marker\n"
    )


@pytest.mark.parametrize("location", ["service", "cwd"])
def test_documented_runtime_posture_check_fails_on_service_dotenv(
    tmp_path,
    location,
) -> None:
    result = _run_documented_runtime_posture_check(
        tmp_path,
        dotenv_in=location,
        ENVIRONMENT="production",
        **_RAILWAY_MARKER,
    )

    assert result.returncode == 1
    assert result.stdout == (
        "[preflight] FAIL runtime posture: a .env file exists where the "
        "service would read it\n"
    )


def test_documented_runtime_posture_check_never_echoes_config_values(tmp_path) -> None:
    """A traceback would print the malformed value; one that carries a
    sentinel line must not reach the output as that line (or at all)."""
    malformed = "runtime-secret\nPRIVATE_RELEASE_CHECKS_OK"
    result = _run_documented_runtime_posture_check(
        tmp_path,
        ENVIRONMENT="production",
        ENABLE_DOGFOOD_TOOL=malformed,
        **_RAILWAY_MARKER,
    )

    assert result.returncode == 1
    assert result.stdout == "[preflight] FAIL runtime posture: ValidationError\n"
    assert result.stderr == ""
    assert "runtime-secret" not in result.stdout + result.stderr
    assert "PRIVATE_RELEASE_CHECKS_OK" not in result.stdout + result.stderr


def test_canonical_railway_sop_uses_immutable_release_context() -> None:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    canonical = sop[
        sop.index("## Canonical deploy path") : sop.index(
            "## Required production variables"
        )
    ]

    assert (
        'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"'
        in canonical
    )
    assert "set -euo pipefail" in canonical
    assert 'test -d "$RELEASE_CONTEXT"' in canonical
    assert (
        'test "$(cat "$RELEASE_CONTEXT/.build_commit_sha")" = "$DEPLOY_SHA"'
        in canonical
    )
    assert 'railway up "$RELEASE_CONTEXT" --path-as-root' in canonical
    canonical_deploy = canonical[canonical.index('railway up "$RELEASE_CONTEXT"') :]
    assert "--no-gitignore" in canonical_deploy
    assert "railway variable set COMMIT_SHA" not in canonical
    assert "--build-arg COMMIT_SHA" not in canonical
    assert "Do not set `COMMIT_SHA` or `BUILD_COMMIT_SHA`" in canonical
    assert "uses `Dockerfile.dev` through `docker-compose.yml`" in canonical
    assert "railway variables" not in sop
    canonical_prepare = canonical.index(
        'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"'
    )
    canonical_deploy = canonical.index('railway up "$RELEASE_CONTEXT"')
    assert canonical.index("set -euo pipefail") < canonical_prepare < canonical_deploy


def test_customer_restore_sop_does_not_misstate_volume_restore_semantics() -> None:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    normalized = " ".join(sop.split())

    assert "Prefer a Railway PITR restore" in normalized
    assert "ordinary Railway volume-backup restore instead swaps" in normalized
    assert "removes backups newer than the selected point" in normalized
    assert "restored disposable target" not in sop


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None

    def json(self):
        return self._payload


# What a production-like boot answers an unauthenticated catalog read with
# since the #444 lockdown (app.core.auth.reject_anonymous_production_catalog).
_MISSING_CREDENTIALS = {
    "detail": {
        "error": "missing_credentials",
        "message": "X-API-Key or Authorization: Bearer header is required.",
        "docs": "/docs",
    }
}


def _is_catalog(url):
    return urlsplit(url).path in preflight._LOCKED_CATALOG_PATHS


def _locked_catalog():
    return _Response(_MISSING_CREDENTIALS, status_code=401)


EXPECTED_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
EXPECTED_SIGNING_KEY_ID = "example-customer-production-ed25519-v1"
EXPECTED_SIGNING_PUBLIC_KEY_SHA256 = (
    "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd"
)
TREE_COMMIT_SHA = preflight._tree_commit_sha()


HEALTHY = {
    "status": "healthy",
    "production_like": True,
    "version": "1.3.0",
    "commit_sha": EXPECTED_COMMIT_SHA,
    "build_provenance": "stamped",
    "unhealthy": [],
    "enable_proof_surfaces": False,
    "enable_dogfood_tool": False,
    "runtime_degradation": {"durable_state": {"fell_back_to_memory": False}},
}


def _manifest_document(**overrides):
    document = {
        "schema_version": "1.0",
        "customer_slug": "example-customer",
        "railway_project_id": "123e4567-e89b-42d3-a456-426614174000",
        "environment": "production",
        "region": "us-west2",
        "public_url": "https://api.example.com",
        "signing_key_id": EXPECTED_SIGNING_KEY_ID,
        "signing_public_key_sha256": EXPECTED_SIGNING_PUBLIC_KEY_SHA256,
        "expected_commit_sha": TREE_COMMIT_SHA,
        "expected_alembic_revision": preflight._tree_head(),
    }
    document.update(overrides)
    return document


def _write_manifest(tmp_path, document):
    path = tmp_path / "customer-manifest.json"
    if isinstance(document, str):
        path.write_text(document)
    else:
        path.write_text(json.dumps(document))
    return path


def _trust_keys(*, kid=EXPECTED_SIGNING_KEY_ID, status="active"):
    return {
        "schema_version": "1.0",
        "issuer": "https://api.example.com",
        "alg": "Ed25519",
        "keys": [
            {
                "kid": kid,
                "status": status,
                "alg": "Ed25519",
                "public_key_b64": base64.b64encode(bytes(range(32))).decode(),
            }
        ],
    }


def _patch_get(monkeypatch, payload):
    import httpx

    def get(url, **_kwargs):
        if _is_catalog(url):
            return _locked_catalog()
        return _Response(payload)

    monkeypatch.setattr(httpx, "get", get)


def _patch_endpoint_get(monkeypatch, dependencies_payload, liveness_payload):
    import httpx

    def get(url, **_kwargs):
        if _is_catalog(url):
            return _locked_catalog()
        payload = (
            dependencies_payload
            if url.endswith("/health/dependencies")
            else liveness_payload
        )
        return _Response(payload)

    monkeypatch.setattr(httpx, "get", get)


def _patch_manifest_get(
    monkeypatch,
    *,
    dependencies_payload=HEALTHY,
    liveness_payload=HEALTHY,
    key_payload=None,
):
    import httpx

    key_payload = key_payload or _trust_keys()

    def get(url, **_kwargs):
        if _is_catalog(url):
            return _locked_catalog()
        if url.endswith("/health/dependencies"):
            return _Response(dependencies_payload)
        if url.endswith("/.well-known/trust-keys.json"):
            return _Response(key_payload)
        return _Response(liveness_payload)

    monkeypatch.setattr(httpx, "get", get)


def test_committed_customer_manifest_template_is_non_secret_and_current():
    path = REPO_ROOT / "docs" / "railway-customer-manifest.example.json"
    document = json.loads(path.read_text())

    assert set(document) == preflight._MANIFEST_FIELDS
    assert document["expected_alembic_revision"] == preflight._tree_head()
    assert not any(
        marker in key.lower()
        for key in document
        for marker in ("secret", "password", "token", "private_key", "database_url")
    )
    assert preflight._load_customer_manifest(path).public_url == (
        "https://api.example.com"
    )


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("{not-json", "readable UTF-8 JSON"),
        ([], "root must be a JSON object"),
        (
            {
                key: value
                for key, value in _manifest_document().items()
                if key != "region"
            },
            "missing required fields: region",
        ),
        (
            {
                key: value
                for key, value in _manifest_document().items()
                if key != "signing_public_key_sha256"
            },
            "missing required fields: signing_public_key_sha256",
        ),
    ],
)
def test_manifest_fails_closed_when_malformed_or_missing(
    tmp_path,
    capsys,
    document,
    message,
):
    path = _write_manifest(tmp_path, document)

    assert preflight.main(["--live", "--manifest", str(path)]) == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("customer_slug", "Example Customer"),
        ("railway_project_id", "not-a-uuid"),
        ("environment", "Production"),
        ("region", "us/west2"),
        ("public_url", "http://api.example.com"),
        ("public_url", "https://api.example.com/customer"),
        ("signing_key_id", "key id with spaces"),
        ("signing_key_id", "a" * 65),
        ("signing_public_key_sha256", "0" * 63),
        ("expected_commit_sha", EXPECTED_COMMIT_SHA[:12]),
        ("expected_alembic_revision", "../031_quotes"),
    ],
)
def test_manifest_rejects_noncanonical_field_formats(tmp_path, field, value):
    path = _write_manifest(tmp_path, _manifest_document(**{field: value}))

    assert preflight.main(["--live", "--manifest", str(path)]) == 1


def test_manifest_rejects_unsupported_fields_without_rendering_values(
    tmp_path,
    capsys,
):
    secret = "postgresql://operator:do-not-print@db.example.com/customer"
    path = _write_manifest(
        tmp_path,
        _manifest_document(database_url=secret),
    )

    assert preflight.main(["--live", "--manifest", str(path)]) == 1
    output = capsys.readouterr().out
    assert "unsupported fields" in output
    assert secret not in output
    assert "do-not-print" not in output


def test_manifest_rejects_tree_revision_mismatch(tmp_path, monkeypatch, capsys):
    path = _write_manifest(
        tmp_path,
        _manifest_document(expected_alembic_revision="030_permit_requests"),
    )
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live check must not run"),
    )

    assert preflight.main(["--live", "--manifest", str(path)]) == 1
    assert "Alembic revision does not match this tree" in capsys.readouterr().out


def test_manifest_rejects_release_checkout_mismatch(tmp_path, monkeypatch, capsys):
    path = _write_manifest(
        tmp_path,
        _manifest_document(expected_commit_sha=EXPECTED_COMMIT_SHA),
    )
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live check must not run"),
    )

    assert preflight.main(["--live", "--manifest", str(path)]) == 1
    assert "does not match this release checkout" in capsys.readouterr().out


def test_manifest_rejects_dirty_release_checkout(tmp_path, monkeypatch, capsys):
    path = _write_manifest(tmp_path, _manifest_document())
    monkeypatch.setattr(preflight, "_tree_is_clean", lambda: False)
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live check must not run"),
    )

    assert preflight.main(["--live", "--manifest", str(path)]) == 1
    output = capsys.readouterr().out
    assert "requires a clean release checkout" in output
    assert "customer-manifest.json" not in output


def test_manifest_rejects_live_url_mismatch(tmp_path, monkeypatch, capsys):
    path = _write_manifest(tmp_path, _manifest_document())
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live check must not run"),
    )

    assert (
        preflight.main(
            [
                "--live",
                "--manifest",
                str(path),
                "--url",
                "https://other.example.com",
            ]
        )
        == 1
    )
    assert "live URL does not match" in capsys.readouterr().out


def test_manifest_rejects_conflicting_expected_commit(tmp_path, capsys):
    path = _write_manifest(tmp_path, _manifest_document())

    assert (
        preflight.main(
            [
                "--live",
                "--manifest",
                str(path),
                "--expected-commit-sha",
                "fedcba9876543210fedcba9876543210fedcba98",
            ]
        )
        == 1
    )
    assert "commit SHA does not match" in capsys.readouterr().out


def test_manifest_supplies_live_url_commit_and_signing_key(
    tmp_path,
    monkeypatch,
):
    path = _write_manifest(tmp_path, _manifest_document())
    seen = []

    def check_live(
        url,
        *,
        expected_version=None,
        expected_commit_sha=None,
        expected_signing_key_id=None,
        expected_signing_public_key_sha256=None,
    ):
        seen.append(
            (
                url,
                expected_version,
                expected_commit_sha,
                expected_signing_key_id,
                expected_signing_public_key_sha256,
            )
        )
        return True

    monkeypatch.setattr(preflight, "check_live", check_live)

    assert preflight.main(["--live", "--strict", "--manifest", str(path)]) == 0
    assert seen == [
        (
            "https://api.example.com",
            None,
            TREE_COMMIT_SHA,
            EXPECTED_SIGNING_KEY_ID,
            EXPECTED_SIGNING_PUBLIC_KEY_SHA256,
        )
    ]


def test_manifest_live_gate_rejects_absent_build_provenance(
    tmp_path,
    monkeypatch,
    capsys,
):
    path = _write_manifest(tmp_path, _manifest_document())
    payload = {**HEALTHY, "commit_sha": TREE_COMMIT_SHA}
    payload.pop("build_provenance")
    _patch_manifest_get(
        monkeypatch,
        dependencies_payload=payload,
        liveness_payload=payload,
    )

    assert preflight.main(["--live", "--strict", "--manifest", str(path)]) == 1
    assert "build_provenance is absent" in capsys.readouterr().out


def test_manifest_only_validates_new_candidate_without_probing_old_release(
    tmp_path,
    monkeypatch,
    capsys,
):
    path = _write_manifest(tmp_path, _manifest_document())
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("old release must not be probed"),
    )
    monkeypatch.setattr(
        preflight,
        "check_db",
        lambda *_args, **_kwargs: pytest.fail("database must not be probed"),
    )

    assert (
        preflight.main(
            [
                "--manifest-only",
                "--manifest",
                str(path),
                "--url",
                "https://api.example.com",
            ]
        )
        == 0
    )
    assert "manifest matches clean release checkout" in capsys.readouterr().out


def test_manifest_only_requires_manifest(capsys):
    assert preflight.main(["--manifest-only"]) == 1
    assert "requires --manifest" in capsys.readouterr().out


@pytest.mark.parametrize(
    "runtime_arguments",
    [
        ["--live"],
        ["--db"],
        ["--public-db"],
        ["--runtime-posture"],
        ["--expected-version", "1.3.0"],
        ["--expected-commit-sha", EXPECTED_COMMIT_SHA],
    ],
)
def test_manifest_only_rejects_runtime_checks(
    tmp_path,
    runtime_arguments,
    capsys,
):
    path = _write_manifest(tmp_path, _manifest_document())
    arguments = ["--manifest-only", "--manifest", str(path), *runtime_arguments]

    assert preflight.main(arguments) == 1
    assert "manifest-only" in capsys.readouterr().out


def test_live_passes_on_expected_posture(monkeypatch):
    _patch_get(monkeypatch, HEALTHY)
    assert preflight.check_live("https://api.example.com") is True


def test_live_passes_on_exact_expected_release_identity(monkeypatch):
    _patch_get(monkeypatch, HEALTHY)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_version="1.3.0",
            expected_commit_sha=EXPECTED_COMMIT_SHA,
        )
        is True
    )


def test_live_uses_public_key_document_when_health_omits_signing_key_id(monkeypatch):
    _patch_manifest_get(monkeypatch)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
            expected_signing_public_key_sha256=(EXPECTED_SIGNING_PUBLIC_KEY_SHA256),
        )
        is True
    )


def test_live_validates_public_key_document_when_health_reports_key_id(monkeypatch):
    _patch_manifest_get(
        monkeypatch,
        dependencies_payload={
            **HEALTHY,
            "signing_key_id": EXPECTED_SIGNING_KEY_ID,
        },
    )

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
            expected_signing_public_key_sha256=(EXPECTED_SIGNING_PUBLIC_KEY_SHA256),
        )
        is True
    )


@pytest.mark.parametrize(
    "key_payload",
    [
        _trust_keys(kid="another-production-ed25519-v1"),
        _trust_keys(status="retired"),
        {"issuer": "https://other.example.com", "keys": []},
        {**_trust_keys(), "alg": "RSA"},
        {
            **_trust_keys(),
            "keys": [
                {
                    "kid": EXPECTED_SIGNING_KEY_ID,
                    "status": "active",
                    "alg": "Ed25519",
                    "public_key_b64": base64.b64encode(b"too-short").decode(),
                }
            ],
        },
        {
            **_trust_keys(),
            "keys": [
                {
                    "kid": EXPECTED_SIGNING_KEY_ID,
                    "status": "active",
                    "alg": "Ed25519",
                    "public_key_b64": "!!!!",
                }
            ],
        },
        {
            **_trust_keys(),
            "keys": [
                {
                    "kid": EXPECTED_SIGNING_KEY_ID,
                    "status": "active",
                    "alg": "Ed25519",
                }
            ],
        },
    ],
    ids=[
        "wrong_key",
        "retired_key",
        "wrong_issuer_and_empty_keys",
        "wrong_algorithm",
        "invalid_public_material",
        "malformed_public_material",
        "missing_public_material",
    ],
)
def test_live_fails_closed_when_public_key_document_mismatches(
    monkeypatch,
    key_payload,
):
    _patch_manifest_get(monkeypatch, key_payload=key_payload)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
            expected_signing_public_key_sha256=(EXPECTED_SIGNING_PUBLIC_KEY_SHA256),
        )
        is False
    )


def test_live_fails_when_health_reports_wrong_signing_key_id(monkeypatch):
    _patch_get(
        monkeypatch,
        {**HEALTHY, "signing_key_id": "another-production-ed25519-v1"},
    )

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
            expected_signing_public_key_sha256=(EXPECTED_SIGNING_PUBLIC_KEY_SHA256),
        )
        is False
    )


def test_live_fails_closed_when_public_key_document_is_unreachable(monkeypatch):
    import httpx

    def get(url, **_kwargs):
        if _is_catalog(url):
            return _locked_catalog()
        if url.endswith("/.well-known/trust-keys.json"):
            raise httpx.ConnectError("no route")
        return _Response({**HEALTHY, "signing_key_id": EXPECTED_SIGNING_KEY_ID})

    monkeypatch.setattr(httpx, "get", get)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
            expected_signing_public_key_sha256=(EXPECTED_SIGNING_PUBLIC_KEY_SHA256),
        )
        is False
    )


def test_live_fails_when_public_key_fingerprint_mismatches(monkeypatch):
    _patch_manifest_get(monkeypatch)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
            expected_signing_public_key_sha256="0" * 64,
        )
        is False
    )


def test_live_fails_when_public_key_fingerprint_is_missing(monkeypatch):
    _patch_manifest_get(monkeypatch)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_signing_key_id=EXPECTED_SIGNING_KEY_ID,
        )
        is False
    )


@pytest.mark.parametrize(
    "override",
    [
        {"status": "degraded"},
        {"production_like": False},
        {"unhealthy": ["postgres"]},
        {"enable_proof_surfaces": True},
        {"enable_dogfood_tool": True},
        {"runtime_degradation": {"durable_state": {"fell_back_to_memory": True}}},
    ],
)
def test_live_fails_on_bad_posture(monkeypatch, override):
    _patch_get(monkeypatch, {**HEALTHY, **override})
    assert preflight.check_live("https://api.example.com") is False


@pytest.mark.parametrize("field", ["enable_proof_surfaces", "runtime_degradation"])
def test_live_rejects_missing_public_posture_field(monkeypatch, capsys, field):
    payload = {key: value for key, value in HEALTHY.items() if key != field}
    _patch_get(monkeypatch, payload)
    assert preflight.check_live("https://api.example.com") is False
    assert "[preflight] PASS" not in capsys.readouterr().out


@pytest.mark.parametrize("value", [None, 0, "", [], {}, "false", True])
def test_live_requires_boolean_false_for_proof_surfaces(monkeypatch, value):
    _patch_get(monkeypatch, {**HEALTHY, "enable_proof_surfaces": value})
    assert preflight.check_live("https://api.example.com") is False


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        [],
        "false",
        {},
        {"durable_state": None},
        {"durable_state": []},
        {"durable_state": "false"},
        {"durable_state": {}},
        {"durable_state": {"fell_back_to_memory": None}},
        {"durable_state": {"fell_back_to_memory": 0}},
        {"durable_state": {"fell_back_to_memory": "false"}},
        {"durable_state": {"fell_back_to_memory": []}},
        {"durable_state": {"fell_back_to_memory": {}}},
    ],
)
def test_live_requires_explicit_durable_posture(monkeypatch, value):
    _patch_get(monkeypatch, {**HEALTHY, "runtime_degradation": value})
    assert preflight.check_live("https://api.example.com") is False


# ---------------------------------------------------------------------------
# Locked-down tool catalogs and the private dogfood posture.
#
# The public /health/dependencies projection omits enable_dogfood_tool (#348),
# and since the #444 Narrow lockdown production-like boots refuse anonymous
# tool catalogs with 401. The live gate therefore asserts the lockdown on every
# catalog route and fails closed on anything else; the dogfood state, no longer
# publicly observable, is asserted privately by --runtime-posture.
# ---------------------------------------------------------------------------


PUBLIC_PROJECTION = {
    key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
}


def _patch_get_with_catalog(monkeypatch, payload, catalog_path, catalog_response):
    import httpx

    def get(url, **_kwargs):
        if urlsplit(url).path == catalog_path:
            if isinstance(catalog_response, Exception):
                raise catalog_response
            return catalog_response
        if _is_catalog(url):
            return _locked_catalog()
        return _Response(payload)

    monkeypatch.setattr(httpx, "get", get)


def test_live_catalog_paths_match_the_locked_production_catalogs():
    """The gate probes every catalog SECURITY_LIMITATIONS.md says #444 locked."""
    limitations = (REPO_ROOT / "SECURITY_LIMITATIONS.md").read_text()
    locked = limitations[limitations.index("tool catalogs (") :]
    locked = locked[: locked.index(")")]

    assert set(preflight._LOCKED_CATALOG_PATHS) == {
        "/v1/discover",
        "/mcp/tools.json",
        "/mcp/tools",
        "/.well-known/mcp/tools.json",
    }
    for path in preflight._LOCKED_CATALOG_PATHS:
        assert f"`{path}`" in locked


def test_live_passes_on_public_projection_with_locked_catalogs(monkeypatch, capsys):
    """The current production posture: no published dogfood flag and every
    tool catalog answering 401 without credentials."""
    _patch_get(monkeypatch, PUBLIC_PROJECTION)

    assert preflight.check_live("https://api.example.com") is True
    output = capsys.readouterr().out
    assert "NOTE enable_dogfood_tool is not published" in output
    assert "--runtime-posture" in output
    assert "dogfood_tool=private" in output
    assert "dogfood_tool=false" not in output
    assert "tool catalogs 401 without credentials" in output


def test_live_reports_published_dogfood_flag_as_verified(monkeypatch, capsys):
    _patch_get(monkeypatch, HEALTHY)

    assert preflight.check_live("https://api.example.com") is True
    output = capsys.readouterr().out
    assert "dogfood_tool=false" in output
    assert "NOTE enable_dogfood_tool" not in output


def test_live_sends_no_credentials_to_catalogs(monkeypatch):
    import httpx

    catalog_calls = []

    def get(url, **kwargs):
        if _is_catalog(url):
            catalog_calls.append((urlsplit(url).path, kwargs))
            return _locked_catalog()
        return _Response(PUBLIC_PROJECTION)

    monkeypatch.setattr(httpx, "get", get)

    assert preflight.check_live("https://api.example.com") is True
    assert sorted(path for path, _ in catalog_calls) == sorted(
        preflight._LOCKED_CATALOG_PATHS
    )
    for _, kwargs in catalog_calls:
        assert set(kwargs) == {"timeout"}


@pytest.mark.parametrize("catalog_path", preflight._LOCKED_CATALOG_PATHS)
@pytest.mark.parametrize(
    "catalog_body",
    [
        {"mcp_tools": [{"service_id": "partner.echo"}]},
        {"mcp_tools": [{"service_id": "partner.notes.write"}]},
        {"mcp_tools": [{"service_id": "partner.echo", "name": "partner.notes.write"}]},
        {"mcp_tools": [{"service_id": ["partner.notes.write"]}]},
        ["not", "a", "dict"],
        {"tools": []},
    ],
    ids=[
        "clean",
        "dogfood_id",
        "dogfood_name",
        "non_string_id",
        "not_a_dict",
        "empty",
    ],
)
@pytest.mark.parametrize(
    "dependencies_payload",
    [PUBLIC_PROJECTION, HEALTHY],
    ids=["public_projection", "published_dogfood_false"],
)
def test_live_fails_when_a_catalog_is_publicly_readable(
    monkeypatch,
    capsys,
    catalog_path,
    catalog_body,
    dependencies_payload,
):
    """The pre-#444 posture must fail the gate: an anonymous 200 catalog is a
    failure whatever it lists, even when every other signal is healthy."""
    _patch_get_with_catalog(
        monkeypatch,
        dependencies_payload,
        catalog_path,
        _Response(catalog_body),
    )

    assert preflight.check_live("https://api.example.com") is False
    output = capsys.readouterr().out
    assert f"{catalog_path} is publicly readable (HTTP 200)" in output
    assert "[preflight] PASS" not in output


@pytest.mark.parametrize("catalog_path", preflight._LOCKED_CATALOG_PATHS)
@pytest.mark.parametrize("status_code", [204, 302, 403, 404, 429, 500, 503])
def test_live_fails_closed_when_catalog_status_is_not_401(
    monkeypatch,
    capsys,
    catalog_path,
    status_code,
):
    """Only 401 proves the lockdown: a redirect, a different refusal, a
    missing route, or an error page cannot, so each fails closed."""
    _patch_get_with_catalog(
        monkeypatch,
        PUBLIC_PROJECTION,
        catalog_path,
        _Response(_MISSING_CREDENTIALS, status_code=status_code),
    )

    assert preflight.check_live("https://api.example.com") is False
    assert catalog_path in capsys.readouterr().out


@pytest.mark.parametrize("catalog_path", preflight._LOCKED_CATALOG_PATHS)
def test_live_fails_closed_when_catalog_is_unreachable(
    monkeypatch,
    capsys,
    catalog_path,
):
    import httpx

    _patch_get_with_catalog(
        monkeypatch,
        PUBLIC_PROJECTION,
        catalog_path,
        httpx.ConnectError("boom"),
    )

    assert preflight.check_live("https://api.example.com") is False
    assert "could not be checked" in capsys.readouterr().out


class _NonJSONResponse(_Response):
    def json(self):
        raise ValueError("response body is not JSON")


def test_catalog_refusal_body_matches_the_application_code(monkeypatch):
    """The body the gate requires is the one #444's code actually returns."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.core import auth, config

    production = config.Settings(_env_file=None, ENVIRONMENT="production")
    monkeypatch.setattr(auth, "get_settings", lambda: production)
    anonymous = Request(
        {"type": "http", "method": "GET", "path": "/v1/discover", "headers": []}
    )

    with pytest.raises(HTTPException) as refused:
        asyncio.run(auth.reject_anonymous_production_catalog(anonymous))

    assert refused.value.status_code == 401
    body = {"detail": refused.value.detail}
    assert body == _MISSING_CREDENTIALS
    assert preflight._is_catalog_refusal(_Response(body, status_code=401))


@pytest.mark.parametrize("catalog_path", preflight._LOCKED_CATALOG_PATHS)
@pytest.mark.parametrize(
    "response",
    [
        _NonJSONResponse(None, status_code=401),
        _Response({"detail": "Not authenticated"}, status_code=401),
        _Response({"detail": {"error": "invalid_credentials"}}, status_code=401),
        _Response({"error": "missing_credentials"}, status_code=401),
        _Response({"detail": {"message": "Unauthorized"}}, status_code=401),
        _Response(["missing_credentials"], status_code=401),
    ],
    ids=[
        "non_json",
        "string_detail",
        "other_error_code",
        "no_detail_wrapper",
        "no_error_code",
        "not_an_object",
    ],
)
def test_live_fails_closed_when_catalog_401_is_not_the_application_refusal(
    monkeypatch,
    capsys,
    catalog_path,
    response,
):
    """An edge, proxy, or platform 401 in front of a public catalog must not
    satisfy the gate: only #444's own missing_credentials refusal does."""
    _patch_get_with_catalog(monkeypatch, PUBLIC_PROJECTION, catalog_path, response)

    assert preflight.check_live("https://api.example.com") is False
    output = capsys.readouterr().out
    assert f"{catalog_path} answered 401 without the application's" in output
    assert "[preflight] PASS" not in output


@pytest.mark.parametrize(
    "value",
    [True, None, "false", 0],
    ids=["true", "null", "string_false", "zero"],
)
@pytest.mark.parametrize(
    "dependencies_payload",
    [HEALTHY, PUBLIC_PROJECTION],
    ids=["published_dogfood_false", "public_projection"],
)
def test_live_fails_when_published_second_dogfood_flag_is_not_false(
    monkeypatch,
    capsys,
    dependencies_payload,
    value,
):
    _patch_get(
        monkeypatch,
        {**dependencies_payload, "enable_dogfood_second_tool": value},
    )

    assert preflight.check_live("https://api.example.com") is False
    assert "enable_dogfood_second_tool=" in capsys.readouterr().out


def test_live_passes_when_published_second_dogfood_flag_is_false(monkeypatch):
    _patch_get(monkeypatch, {**HEALTHY, "enable_dogfood_second_tool": False})

    assert preflight.check_live("https://api.example.com") is True


def test_live_fails_when_production_posture_is_missing(monkeypatch):
    payload = {key: value for key, value in HEALTHY.items() if key != "production_like"}
    _patch_get(monkeypatch, payload)

    assert preflight.check_live("https://api.example.com") is False


@pytest.mark.parametrize(
    ("field", "expected_value"),
    [
        ("version", "1.3.0"),
        ("commit_sha", EXPECTED_COMMIT_SHA),
    ],
)
def test_live_fails_when_expected_release_identity_is_missing(
    monkeypatch,
    field,
    expected_value,
):
    payload = {key: value for key, value in HEALTHY.items() if key != field}
    _patch_get(monkeypatch, payload)
    kwargs = {
        "expected_version": expected_value if field == "version" else None,
        "expected_commit_sha": expected_value if field == "commit_sha" else None,
    }

    assert preflight.check_live("https://api.example.com", **kwargs) is False


@pytest.mark.parametrize(
    ("field", "actual_value", "kwargs"),
    [
        ("version", "1.2.0", {"expected_version": "1.3.0"}),
        (
            "commit_sha",
            "fedcba9876543210fedcba9876543210fedcba98",
            {"expected_commit_sha": EXPECTED_COMMIT_SHA},
        ),
    ],
)
def test_live_fails_when_expected_release_identity_mismatches(
    monkeypatch,
    field,
    actual_value,
    kwargs,
):
    _patch_get(monkeypatch, {**HEALTHY, field: actual_value})

    assert preflight.check_live("https://api.example.com", **kwargs) is False


@pytest.mark.parametrize(
    ("field", "actual_value", "kwargs"),
    [
        ("version", "1.2.0", {"expected_version": "1.3.0"}),
        (
            "commit_sha",
            "fedcba9876543210fedcba9876543210fedcba98",
            {"expected_commit_sha": EXPECTED_COMMIT_SHA},
        ),
    ],
)
def test_live_fails_when_liveness_release_identity_mismatches(
    monkeypatch,
    field,
    actual_value,
    kwargs,
):
    _patch_endpoint_get(
        monkeypatch,
        HEALTHY,
        {**HEALTHY, field: actual_value},
    )

    assert preflight.check_live("https://api.example.com", **kwargs) is False


def test_live_rejects_abbreviated_expected_commit_sha(monkeypatch):
    _patch_get(monkeypatch, HEALTHY)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_commit_sha=EXPECTED_COMMIT_SHA[:12],
        )
        is False
    )


def test_cli_forwards_expected_release_identity(monkeypatch):
    seen = []

    def check_live(url, *, expected_version=None, expected_commit_sha=None):
        seen.append((url, expected_version, expected_commit_sha))
        return True

    monkeypatch.setattr(preflight, "check_live", check_live)

    assert (
        preflight.main(
            [
                "--live",
                "--strict",
                "--url",
                "https://api.example.com",
                "--expected-version",
                "1.3.0",
                "--expected-commit-sha",
                EXPECTED_COMMIT_SHA,
            ]
        )
        == 0
    )
    assert seen == [("https://api.example.com", "1.3.0", EXPECTED_COMMIT_SHA)]


def test_live_fails_when_unreachable(monkeypatch):
    import httpx

    def _boom(*_args, **_kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", _boom)
    assert preflight.check_live("https://api.example.com") is False


def test_live_fails_when_dogfood_flag_published_as_null(monkeypatch):
    """A *published* null is not the post-#348 omission: the exactly-false
    requirement still applies, even with every catalog locked."""
    _patch_get(monkeypatch, {**HEALTHY, "enable_dogfood_tool": None})

    assert preflight.check_live("https://api.example.com") is False


# ---------------------------------------------------------------------------
# Private runtime posture (--runtime-posture).
#
# The dogfood state is no longer publicly observable, so the private release
# path asserts it inside the deployed API container from the same settings
# the running service resolves. Outside a production-like runtime it must fail
# closed rather than pass on a developer machine's defaults.
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime_settings(monkeypatch, tmp_path):
    """A deployed Railway container's variables, from this test only.

    Every Railway marker is cleared first. The check runs from an empty
    working directory (``tmp_path / "cwd"``), and the service's own working
    directory, which the image puts at the script's ``REPO_ROOT``, is an empty
    ``tmp_path / "service"``. A value of None unsets that variable.
    """
    from app.core.trust_mode import HOSTED_RUNTIME_MARKER_VARS

    (tmp_path / "cwd").mkdir()
    (tmp_path / "service").mkdir()
    monkeypatch.chdir(tmp_path / "cwd")
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path / "service")
    for marker in HOSTED_RUNTIME_MARKER_VARS:
        monkeypatch.delenv(marker, raising=False)

    def configure(**environment):
        values = {
            "RAILWAY_SERVICE_ID": "0f0e0d0c-api-service",
            "ENVIRONMENT": "production",
            "ENABLE_DOGFOOD_TOOL": "false",
            "ENABLE_DOGFOOD_SECOND_TOOL": "false",
            **environment,
        }
        for name, value in values.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

    return configure


def test_runtime_posture_passes_in_production_with_dogfood_off(
    runtime_settings,
    capsys,
):
    runtime_settings()

    assert preflight.check_runtime_posture() is True
    output = capsys.readouterr().out
    assert "ENABLE_DOGFOOD_TOOL=false" in output
    assert "ENABLE_DOGFOOD_SECOND_TOOL=false" in output


@pytest.mark.parametrize(
    "environment",
    [
        {"ENABLE_DOGFOOD_TOOL": "true"},
        {"ENABLE_DOGFOOD_SECOND_TOOL": "true"},
        {"ENABLE_DOGFOOD_TOOL": "1", "ENABLE_DOGFOOD_SECOND_TOOL": "yes"},
    ],
    ids=["dogfood_tool", "dogfood_second_tool", "both"],
)
def test_runtime_posture_fails_when_dogfood_tool_is_enabled(
    runtime_settings,
    capsys,
    environment,
):
    runtime_settings(**environment)

    assert preflight.check_runtime_posture() is False
    output = capsys.readouterr().out
    for flag in environment:
        assert f"{flag} is enabled" in output
    assert "[preflight] PASS" not in output


@pytest.mark.parametrize("environment", ["local", "test", "development"])
def test_runtime_posture_fails_closed_outside_production_runtime(
    runtime_settings,
    capsys,
    environment,
):
    """Dogfood off by default on a laptop proves nothing about production."""
    runtime_settings(ENVIRONMENT=environment)

    assert preflight.check_runtime_posture() is False
    assert "ENVIRONMENT is not production-like" in capsys.readouterr().out


@pytest.mark.parametrize("environment", ["production", "banana"])
@pytest.mark.parametrize(
    "marker_value",
    [None, "", "   "],
    ids=["unset", "empty", "blank"],
)
def test_runtime_posture_fails_closed_without_railway_runtime_marker(
    runtime_settings,
    capsys,
    environment,
    marker_value,
):
    """A production-like ENVIRONMENT alone (any unrecognized value counts)
    proves nothing about the deployed service."""
    runtime_settings(ENVIRONMENT=environment, RAILWAY_SERVICE_ID=marker_value)

    assert preflight.check_runtime_posture() is False
    output = capsys.readouterr().out
    assert "no Railway runtime marker" in output
    assert "[preflight] PASS" not in output


def _hosted_runtime_marker_vars():
    from app.core.trust_mode import HOSTED_RUNTIME_MARKER_VARS

    return HOSTED_RUNTIME_MARKER_VARS


@pytest.mark.parametrize("marker", _hosted_runtime_marker_vars())
def test_runtime_posture_accepts_each_railway_runtime_marker(runtime_settings, marker):
    runtime_settings(**{"RAILWAY_SERVICE_ID": None, marker: "railway-value"})

    assert preflight.check_runtime_posture() is True


def test_runtime_posture_ignores_dotenv_in_working_directory(
    runtime_settings,
    tmp_path,
    capsys,
):
    """A scratch .env must not be able to vouch for production: it is never
    read, and its presence alone fails the check."""
    (tmp_path / "cwd" / ".env").write_text(
        "ENVIRONMENT=production\n"
        "ENABLE_DOGFOOD_TOOL=false\n"
        "ENABLE_DOGFOOD_SECOND_TOOL=false\n"
    )
    runtime_settings(ENVIRONMENT=None)

    assert preflight.check_runtime_posture() is False
    output = capsys.readouterr().out
    assert "ENVIRONMENT is not production-like" in output
    assert "exists and the service would read it" in output


@pytest.mark.parametrize("location", ["service", "cwd"])
def test_runtime_posture_fails_when_the_service_would_read_a_dotenv(
    runtime_settings,
    tmp_path,
    capsys,
    location,
):
    """get_settings() reads .env from the service's working directory. The
    check reads only the process environment, so a .env there (even one that
    agrees) means the check cannot vouch for the service's configuration."""
    dotenv = tmp_path / location / ".env"
    dotenv.write_text("ENABLE_DOGFOOD_TOOL=false\n")
    runtime_settings()

    assert preflight.check_runtime_posture() is False
    output = capsys.readouterr().out
    assert f"{dotenv} exists and the service would read it" in output
    assert "[preflight] PASS" not in output


def test_runtime_posture_is_not_blocked_by_other_dotenv_files(
    runtime_settings,
    tmp_path,
):
    """Negative control: only a file named .env is read by the service."""
    for location in ("service", "cwd"):
        (tmp_path / location / ".env.example").write_text("ENVIRONMENT=local\n")
    runtime_settings()

    assert preflight.check_runtime_posture() is True


def test_runtime_image_never_contains_a_dotenv_file():
    """Ignoring .env equals what the service resolves only because the image
    build context never includes one."""
    patterns = {
        line.strip() for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
    }

    assert {".env", ".env.*"} <= patterns


def test_runtime_posture_fails_closed_without_rendering_config_errors(
    runtime_settings,
    capsys,
):
    """A malformed value fails validation; its message would echo the value."""
    secret = "postgresql://user:runtime-secret@postgres.railway.internal/db"
    runtime_settings(ENABLE_DOGFOOD_TOOL=secret)

    assert preflight.check_runtime_posture() is False
    output = capsys.readouterr().out
    assert "unable to resolve the runtime configuration (ValidationError)" in output
    assert "runtime-secret" not in output


def test_cli_runtime_posture_runs_only_the_private_check(monkeypatch):
    seen = []
    monkeypatch.setattr(
        preflight,
        "check_runtime_posture",
        lambda: seen.append("runtime") is None,
    )
    monkeypatch.setattr(
        preflight,
        "check_db",
        lambda *_args, **_kwargs: pytest.fail("database must not be probed"),
    )
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live service must not be probed"),
    )

    assert preflight.main(["--runtime-posture", "--strict"]) == 0
    assert seen == ["runtime"]


def test_cli_private_release_check_fails_when_runtime_posture_fails(monkeypatch):
    """The in-container SOP command fails even when schema parity passes."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db.internal/app")
    monkeypatch.setattr(preflight, "check_db", lambda _url: True)
    monkeypatch.setattr(preflight, "check_runtime_posture", lambda: False)
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live service must not be probed"),
    )

    assert preflight.main(["--db", "--runtime-posture", "--strict"]) == 1


def test_cli_default_run_never_includes_runtime_posture(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        preflight,
        "check_runtime_posture",
        lambda: pytest.fail("runtime posture must be requested explicitly"),
    )

    assert preflight.main(["--url", ""]) == 0


@pytest.mark.parametrize(
    "selectors",
    [[], ["--db"], ["--live"], ["--runtime-posture"], ["--live", "--runtime-posture"]],
    ids=["alone", "db", "live", "runtime_posture", "live_and_runtime_posture"],
)
def test_cli_public_db_fails_closed_whatever_else_is_selected(
    monkeypatch,
    capsys,
    selectors,
):
    """--public-db must never be switched off by another selector: with no
    DATABASE_PUBLIC_URL the run fails, as `--public-db --strict` always has."""
    private_secret = "postgresql://user:private-secret@postgres.railway.internal/db"
    monkeypatch.setenv("DATABASE_URL", private_secret)
    monkeypatch.delenv("DATABASE_PUBLIC_URL", raising=False)
    monkeypatch.setattr(preflight, "check_runtime_posture", lambda: True)
    monkeypatch.setattr(preflight, "check_live", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        preflight,
        "check_db",
        lambda *_args, **_kwargs: pytest.fail("no public URL, nothing to probe"),
    )

    arguments = ["--public-db", *selectors, "--strict"]
    arguments += ["--url", "https://api.example.com"]
    assert preflight.main(arguments) == 1
    output = capsys.readouterr().out
    assert "DATABASE_PUBLIC_URL is required" in output
    assert "all checks passed" not in output
    assert "private-secret" not in output


@pytest.mark.parametrize(
    "selectors",
    [["--runtime-posture"], ["--live"]],
    ids=["runtime_posture", "live"],
)
def test_cli_public_db_checks_the_public_url_alongside_other_checks(
    monkeypatch,
    selectors,
):
    public_url = "postgresql://user:public-secret@switchback.proxy.rlwy.net:5432/db"
    seen = []
    monkeypatch.setenv("DATABASE_PUBLIC_URL", public_url)
    monkeypatch.setattr(preflight, "check_db", lambda url: seen.append(url) is None)
    monkeypatch.setattr(preflight, "check_runtime_posture", lambda: True)
    monkeypatch.setattr(preflight, "check_live", lambda *_args, **_kwargs: True)

    arguments = ["--public-db", *selectors, "--strict"]
    arguments += ["--url", "https://api.example.com"]
    assert preflight.main(arguments) == 0
    assert seen == [public_url]


@pytest.mark.parametrize(
    "live_only_option",
    [
        ["--expected-version", "1.3.0"],
        ["--expected-commit-sha", EXPECTED_COMMIT_SHA],
        ["--manifest", "MANIFEST"],
    ],
    ids=["expected_version", "expected_commit_sha", "manifest"],
)
@pytest.mark.parametrize(
    "selectors",
    [
        ["--runtime-posture"],
        ["--db", "--runtime-posture"],
        ["--db"],
        ["--db", "--public-db"],
    ],
    ids=["runtime_posture", "db_and_runtime_posture", "db", "db_and_public_db"],
)
def test_cli_selectors_reject_live_only_options_without_live(
    tmp_path,
    monkeypatch,
    capsys,
    live_only_option,
    selectors,
):
    """Without --live these would be dropped silently while the run looked
    like it had checked the release identity."""
    manifest = _write_manifest(tmp_path, _manifest_document())
    option = [str(manifest) if arg == "MANIFEST" else arg for arg in live_only_option]
    for check in ("check_runtime_posture", "check_db", "check_live"):
        monkeypatch.setattr(
            preflight,
            check,
            lambda *_args, **_kwargs: pytest.fail("a usage error runs no check"),
        )

    assert preflight.main([*selectors, "--strict", *option]) == 1
    assert "apply only to --live" in capsys.readouterr().out


@pytest.mark.parametrize(
    "selectors", [[], ["--db", "--live"], ["--live", "--runtime-posture"]]
)
def test_cli_selected_live_check_keeps_release_expectations(monkeypatch, selectors):
    seen = []
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///unused.db")
    monkeypatch.setattr(preflight, "check_db", lambda _url: seen.append("db") is None)
    monkeypatch.setattr(
        preflight,
        "check_runtime_posture",
        lambda: seen.append("runtime") is None,
    )

    def check_live(url, *, expected_version=None, expected_commit_sha=None):
        seen.append((url, expected_version, expected_commit_sha))
        return True

    monkeypatch.setattr(preflight, "check_live", check_live)

    arguments = [*selectors, "--strict"]
    arguments += ["--url", "https://api.example.com"]
    arguments += ["--expected-version", "1.3.0"]
    arguments += ["--expected-commit-sha", EXPECTED_COMMIT_SHA]
    assert preflight.main(arguments) == 0
    expected_checks = ["runtime"] if "--runtime-posture" in selectors else ["db"]
    assert seen == [
        *expected_checks,
        ("https://api.example.com", "1.3.0", EXPECTED_COMMIT_SHA),
    ]


_SIGNING_ARGUMENTS = [
    "--expected-signing-key-id",
    EXPECTED_SIGNING_KEY_ID,
    "--expected-signing-public-key-sha256",
    EXPECTED_SIGNING_PUBLIC_KEY_SHA256,
]


def test_cli_forwards_explicit_signing_key_expectations(monkeypatch):
    seen = []

    def check_live(url, **expectations):
        seen.append((url, expectations))
        return True

    monkeypatch.setattr(preflight, "check_live", check_live)

    arguments = ["--live", "--strict", "--url", "https://api.example.com"]
    arguments += ["--expected-version", "1.3.0"]
    arguments += ["--expected-commit-sha", EXPECTED_COMMIT_SHA, *_SIGNING_ARGUMENTS]
    assert preflight.main(arguments) == 0
    assert seen == [
        (
            "https://api.example.com",
            {
                "expected_version": "1.3.0",
                "expected_commit_sha": EXPECTED_COMMIT_SHA,
                "expected_signing_key_id": EXPECTED_SIGNING_KEY_ID,
                "expected_signing_public_key_sha256": (
                    EXPECTED_SIGNING_PUBLIC_KEY_SHA256
                ),
            },
        )
    ]


@pytest.mark.parametrize(
    ("signing_arguments", "passes"),
    [
        (_SIGNING_ARGUMENTS, True),
        (
            ["--expected-signing-key-id", EXPECTED_SIGNING_KEY_ID]
            + ["--expected-signing-public-key-sha256", "0" * 64],
            False,
        ),
        (
            ["--expected-signing-key-id", "another-production-ed25519-v1"]
            + ["--expected-signing-public-key-sha256"]
            + [EXPECTED_SIGNING_PUBLIC_KEY_SHA256],
            False,
        ),
    ],
    ids=["published_key_matches", "wrong_fingerprint", "wrong_key_id"],
)
def test_cli_signing_key_expectations_verify_the_published_key(
    monkeypatch,
    capsys,
    signing_arguments,
    passes,
):
    """The flags run the same trust-key check the manifest does (the
    wrong-fingerprint and wrong-id cases are the negative controls)."""
    _patch_manifest_get(monkeypatch)

    arguments = ["--live", "--strict", "--url", "https://api.example.com"]
    assert preflight.main([*arguments, *signing_arguments]) == (0 if passes else 1)
    output = capsys.readouterr().out
    verified = (
        f"signing key {EXPECTED_SIGNING_KEY_ID} published with the expected "
        "public-key fingerprint"
    )
    if passes:
        assert verified in output
    else:
        assert "not published exactly once as an active Ed25519 key" in output
        assert verified not in output


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ["--live", "--expected-signing-key-id", EXPECTED_SIGNING_KEY_ID],
            "must be given together",
        ),
        (
            ["--live", "--expected-signing-public-key-sha256"]
            + [EXPECTED_SIGNING_PUBLIC_KEY_SHA256],
            "must be given together",
        ),
        (
            ["--live", "--expected-signing-key-id", "Key With Spaces"]
            + ["--expected-signing-public-key-sha256"]
            + [EXPECTED_SIGNING_PUBLIC_KEY_SHA256],
            "must be a lowercase safe identifier",
        ),
        (
            ["--live", "--expected-signing-key-id", EXPECTED_SIGNING_KEY_ID]
            + ["--expected-signing-public-key-sha256", "0" * 63],
            "must be a lowercase SHA-256 digest",
        ),
        (
            ["--live", "--expected-signing-key-id", EXPECTED_SIGNING_KEY_ID]
            + ["--expected-signing-public-key-sha256"]
            + [EXPECTED_SIGNING_PUBLIC_KEY_SHA256.upper()],
            "must be a lowercase SHA-256 digest",
        ),
        (
            ["--live", "--expected-signing-key-id", ""]
            + ["--expected-signing-public-key-sha256", ""],
            "must be a lowercase safe identifier",
        ),
        (
            ["--live", "--manifest", "MANIFEST", *_SIGNING_ARGUMENTS],
            "cannot be combined with --manifest",
        ),
        (_SIGNING_ARGUMENTS, "apply only to --live"),
        (["--db", *_SIGNING_ARGUMENTS], "apply only to --live"),
        (["--runtime-posture", *_SIGNING_ARGUMENTS], "apply only to --live"),
        (
            ["--manifest-only", "--manifest", "MANIFEST", *_SIGNING_ARGUMENTS],
            "--manifest-only cannot be combined",
        ),
    ],
    ids=[
        "key_id_alone",
        "fingerprint_alone",
        "malformed_key_id",
        "short_fingerprint",
        "uppercase_fingerprint",
        "empty_values",
        "with_manifest",
        "default_run",
        "db_only",
        "runtime_posture_only",
        "manifest_only",
    ],
)
def test_cli_rejects_invalid_signing_key_expectations(
    tmp_path,
    monkeypatch,
    capsys,
    arguments,
    message,
):
    manifest = _write_manifest(tmp_path, _manifest_document())
    arguments = [str(manifest) if arg == "MANIFEST" else arg for arg in arguments]
    for check in ("check_runtime_posture", "check_db", "check_live"):
        monkeypatch.setattr(
            preflight,
            check,
            lambda *_args, **_kwargs: pytest.fail("a usage error runs no check"),
        )

    assert preflight.main([*arguments, "--url", "https://api.example.com"]) == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(
    "expectations",
    [
        _SIGNING_ARGUMENTS,
        ["--expected-version", "1.3.0"],
        ["--expected-commit-sha", EXPECTED_COMMIT_SHA],
        ["--expected-version", "1.3.0", "--expected-commit-sha", EXPECTED_COMMIT_SHA],
    ],
    ids=["signing_key", "version", "commit_sha", "release_identity"],
)
@pytest.mark.parametrize(
    "url_arguments",
    [["--url", ""], ["--url", "   "], []],
    ids=["empty_url", "blank_url", "no_url"],
)
@pytest.mark.parametrize("strict", [[], ["--strict"]], ids=["lenient", "strict"])
def test_cli_fails_when_live_expectations_have_no_url(
    monkeypatch,
    capsys,
    expectations,
    url_arguments,
    strict,
):
    """An expectation that is never checked must not pass, --strict or not."""
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("there is no URL to probe"),
    )

    assert preflight.main(["--live", *strict, *url_arguments, *expectations]) == 1
    output = capsys.readouterr().out
    assert "cannot be checked" in output
    assert "all checks passed" not in output


@pytest.mark.parametrize(
    ("strict", "expected_rc"),
    [([], 0), (["--strict"], 1)],
    ids=["lenient_skip_passes", "strict_skip_fails"],
)
def test_cli_live_without_url_or_expectations_still_skips(
    monkeypatch,
    capsys,
    strict,
    expected_rc,
):
    """Negative control: with nothing expected, a missing URL stays a skip."""
    monkeypatch.delenv("PUBLIC_URL", raising=False)

    assert preflight.main(["--live", *strict, "--url", ""]) == expected_rc
    output = capsys.readouterr().out
    assert "SKIP live posture: no PUBLIC_URL and no --url" in output
    assert "cannot be checked" not in output


# ---------------------------------------------------------------------------
# Build provenance gate.
#
# The reported SHA says which commit is live; provenance says whether the image
# came through `railway up --build-arg COMMIT_SHA=...`. Only "stamped" can come
# from that path, so every other value must fail the gate rather than pass on
# an accurate-looking SHA.
# ---------------------------------------------------------------------------


def test_live_passes_on_stamped_provenance(monkeypatch, capsys):
    _patch_get(monkeypatch, {**HEALTHY, "build_provenance": "stamped"})

    assert preflight.check_live("https://api.example.com") is True
    assert "build_provenance" not in capsys.readouterr().out


def test_live_notes_absent_provenance_without_failing(monkeypatch, capsys):
    """An older image predates the field. That is unverified, not bad - it must
    be visible, but must not block deploying an image built before the field
    existed."""
    payload = {key: value for key, value in HEALTHY.items()}
    payload.pop("build_provenance", None)
    _patch_get(monkeypatch, payload)

    assert preflight.check_live("https://api.example.com") is True
    output = capsys.readouterr().out
    assert "NOTE" in output
    assert "build_provenance absent" in output


def test_live_rejects_absent_provenance_for_exact_release(monkeypatch, capsys):
    payload = {key: value for key, value in HEALTHY.items()}
    payload.pop("build_provenance")
    _patch_get(monkeypatch, payload)

    assert (
        preflight.check_live(
            "https://api.example.com",
            expected_commit_sha=EXPECTED_COMMIT_SHA,
        )
        is False
    )
    output = capsys.readouterr().out
    assert "build_provenance is absent" in output
    assert "NOTE build_provenance" not in output


@pytest.mark.parametrize(
    "provenance",
    ["mismatch", "control_plane_only", "unstamped"],
)
def test_live_rejects_unstamped_provenance(monkeypatch, capsys, provenance):
    _patch_get(monkeypatch, {**HEALTHY, "build_provenance": provenance})

    assert preflight.check_live("https://api.example.com") is False

    output = capsys.readouterr().out
    assert "build_provenance" in output
    assert provenance in output


def test_live_rejects_unrecognized_provenance_value(monkeypatch):
    """Fail closed on a value this gate does not know: a renamed or future
    classification must not read as approval."""
    _patch_get(monkeypatch, {**HEALTHY, "build_provenance": "something_new"})

    assert preflight.check_live("https://api.example.com") is False


def test_live_rejects_explicit_null_provenance(monkeypatch, capsys):
    """A published null is not an absent key.

    `body.get()` would conflate the two and route an explicit null onto the
    older-image note path, letting a build with no provenance value pass the
    gate. The field is present and does not say "stamped", so it fails closed -
    matching how the dogfood check treats a published null.
    """
    _patch_get(monkeypatch, {**HEALTHY, "build_provenance": None})

    assert preflight.check_live("https://api.example.com") is False

    output = capsys.readouterr().out
    assert "build_provenance" in output
    assert "NOTE" not in output
