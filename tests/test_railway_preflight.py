"""Deploy-gate coverage for scripts/railway_preflight.py.

The preflight only earns its place if it fails on the states that actually
break a Railway deploy: a tree ahead of the deployed schema, a database
bootstrapped by ``create_all`` and never stamped, and a service that came up
with memory state or proof surfaces on.
"""

import asyncio
import base64
import importlib.util
import json
import socket
from pathlib import Path

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


def _dns_answer(address, *, port=443):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    socket_address = (
        (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    )
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", socket_address)


@pytest.fixture(autouse=True)
def deterministic_public_dns(monkeypatch):
    """Keep credential-routing tests independent of the machine's DNS."""
    answers = {
        "api.example.com": (
            _dns_answer("93.184.216.34"),
            _dns_answer("2606:2800:220:1:248:1893:25c8:1946"),
        ),
        "127.0.0.1.nip.io": (_dns_answer("127.0.0.1"),),
    }

    def getaddrinfo(host, port, *_args, **_kwargs):
        try:
            records = answers[host]
        except KeyError as exc:
            raise socket.gaierror(f"unexpected test hostname: {host}") from exc
        assert port == 443
        return records

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


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


def test_fails_on_unstamped_create_all_bootstrap(migrated_db):
    """Tables present, no alembic_version row — needs `alembic stamp head`."""
    async_url, sync_url = migrated_db
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    assert preflight.check_db(async_url) is False


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


@pytest.fixture
def unbound_railway_status():
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "environments": {
            "edges": [
                {
                    "node": {
                        "name": "production",
                        "serviceInstances": {
                            "edges": [
                                {
                                    "node": {
                                        "serviceName": "api-service",
                                        "source": {"repo": None, "image": None},
                                    }
                                }
                            ]
                        },
                    }
                }
            ]
        },
    }


def test_railway_source_gate_accepts_unbound_service(unbound_railway_status):
    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is True
    )


@pytest.mark.parametrize(
    "source",
    [
        {"repo": "PetrefiedThunder/agent-middleware-api", "image": None},
        {"repo": None, "image": "ghcr.io/example/agent-middleware-api:latest"},
    ],
)
def test_railway_source_gate_rejects_bound_service(unbound_railway_status, source):
    service = unbound_railway_status["environments"]["edges"][0]["node"][
        "serviceInstances"
    ]["edges"][0]["node"]
    service["source"] = source

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


def test_railway_source_gate_rejects_wrong_project(unbound_railway_status):
    unbound_railway_status["id"] = "22222222-2222-4222-8222-222222222222"

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


@pytest.mark.parametrize("environment", ["missing", "staging"])
def test_railway_source_gate_rejects_missing_or_wrong_environment(
    unbound_railway_status, environment
):
    if environment == "missing":
        unbound_railway_status["environments"]["edges"] = []
    else:
        unbound_railway_status["environments"]["edges"][0]["node"]["name"] = "staging"

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


def test_railway_source_gate_rejects_duplicate_environment(unbound_railway_status):
    duplicate = json.loads(
        json.dumps(unbound_railway_status["environments"]["edges"][0])
    )
    unbound_railway_status["environments"]["edges"].append(duplicate)

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


@pytest.mark.parametrize("service_name", [None, "worker"])
def test_railway_source_gate_rejects_missing_or_wrong_service(
    unbound_railway_status, service_name
):
    services = unbound_railway_status["environments"]["edges"][0]["node"][
        "serviceInstances"
    ]["edges"]
    if service_name is None:
        services.clear()
    else:
        services[0]["node"]["serviceName"] = service_name

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


def test_railway_source_gate_rejects_duplicate_service(unbound_railway_status):
    services = unbound_railway_status["environments"]["edges"][0]["node"][
        "serviceInstances"
    ]["edges"]
    services.append(json.loads(json.dumps(services[0])))

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


@pytest.mark.parametrize(
    "source",
    [
        {},
        {"repo": None},
        {"image": None},
        [],
    ],
)
def test_railway_source_gate_rejects_missing_or_malformed_source(
    unbound_railway_status, source
):
    service = unbound_railway_status["environments"]["edges"][0]["node"][
        "serviceInstances"
    ]["edges"][0]["node"]
    service["source"] = source

    assert (
        preflight.validate_railway_source_unbound(
            unbound_railway_status,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"id": "11111111-1111-4111-8111-111111111111", "environments": None},
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "environments": {"edges": "not-a-list"},
        },
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "environments": {"edges": [{}]},
        },
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "environments": {"edges": [{"node": {"name": "production"}}]},
        },
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "environments": {
                "edges": [
                    {
                        "node": {
                            "name": "production",
                            "serviceInstances": {"edges": [{}]},
                        }
                    }
                ]
            },
        },
    ],
)
def test_railway_source_gate_rejects_malformed_status(document):
    assert (
        preflight.validate_railway_source_unbound(
            document,
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )


def test_railway_source_check_uses_exact_read_only_command(
    unbound_railway_status, monkeypatch
):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return preflight.subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(unbound_railway_status),
            stderr="",
        )

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    assert (
        preflight.check_railway_source_unbound(
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is True
    )
    assert seen["command"] == [
        "railway",
        "status",
        "--project",
        "11111111-1111-4111-8111-111111111111",
        "--environment",
        "production",
        "--json",
    ]
    assert seen["kwargs"] == {
        "cwd": preflight.REPO_ROOT,
        "shell": False,
        "capture_output": True,
        "text": True,
        "timeout": 15,
        "check": False,
    }


@pytest.mark.parametrize("stdout", ["", "{", "{}{}", "[]", '"text"'])
def test_railway_source_check_rejects_invalid_stdout(stdout, monkeypatch, capsys):
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda command, **_kwargs: preflight.subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout,
            stderr="",
        ),
    )

    assert (
        preflight.check_railway_source_unbound(
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )
    assert "could not be verified" in capsys.readouterr().out


def test_railway_source_check_hides_nonzero_output(monkeypatch, capsys):
    secret = "railway_token=secret-token-shaped-value"
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda command, **_kwargs: preflight.subprocess.CompletedProcess(
            command,
            1,
            stdout=secret,
            stderr=secret,
        ),
    )

    assert (
        preflight.check_railway_source_unbound(
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )
    output = capsys.readouterr().out
    assert "could not be verified" in output
    assert secret not in output


def test_railway_source_check_hides_cli_os_error(monkeypatch, capsys):
    secret = "railway_token=secret-token-shaped-value"

    def fail(*_args, **_kwargs):
        raise OSError(secret)

    monkeypatch.setattr(preflight.subprocess, "run", fail)

    assert (
        preflight.check_railway_source_unbound(
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )
    output = capsys.readouterr().out
    assert "could not be verified" in output
    assert secret not in output


def test_railway_source_check_hides_cli_timeout(monkeypatch, capsys):
    secret = "railway_token=secret-token-shaped-value"

    def timeout(command, **_kwargs):
        raise preflight.subprocess.TimeoutExpired(
            command,
            timeout=15,
            output=secret,
            stderr=secret,
        )

    monkeypatch.setattr(preflight.subprocess, "run", timeout)

    assert (
        preflight.check_railway_source_unbound(
            project_id="11111111-1111-4111-8111-111111111111",
            environment="production",
            service="api-service",
        )
        is False
    )
    output = capsys.readouterr().out
    assert "could not be verified" in output
    assert secret not in output


@pytest.mark.parametrize("check_result, expected_exit", [(True, 0), (False, 1)])
def test_railway_source_mode_runs_only_provider_guard(
    check_result, expected_exit, monkeypatch
):
    seen = []
    monkeypatch.setattr(
        preflight,
        "check_railway_source_unbound",
        lambda **kwargs: seen.append(kwargs) is None and check_result,
    )
    monkeypatch.setattr(
        preflight,
        "check_db",
        lambda *_args, **_kwargs: pytest.fail("database check must not run"),
    )
    monkeypatch.setattr(
        preflight,
        "check_live",
        lambda *_args, **_kwargs: pytest.fail("live check must not run"),
    )

    assert (
        preflight.main(
            [
                "--railway-source-unbound",
                "--railway-project",
                "11111111-1111-4111-8111-111111111111",
                "--railway-environment",
                "production",
                "--railway-service",
                "api-service",
            ]
        )
        == expected_exit
    )
    assert seen == [
        {
            "project_id": "11111111-1111-4111-8111-111111111111",
            "environment": "production",
            "service": "api-service",
        }
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--railway-environment", "production"],
        ["--railway-project", "11111111-1111-4111-8111-111111111111"],
    ],
)
def test_railway_source_mode_requires_project_and_environment(
    arguments, monkeypatch, capsys
):
    monkeypatch.setattr(
        preflight,
        "check_railway_source_unbound",
        lambda **_kwargs: pytest.fail("incomplete target must not be checked"),
    )

    assert preflight.main(["--railway-source-unbound", *arguments]) == 1
    assert "requires --railway-project and --railway-environment" in (
        capsys.readouterr().out
    )


def test_release_workflow_validates_without_production_mutation() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "railway-deploy.yml").read_text()

    resolve = workflow.index("- name: Resolve release identity")
    ci_gate = workflow.index("- name: Require green CI for exact commit")
    posture = workflow.index("- name: Preflight — current production posture")
    clean = workflow.index("- name: Confirm source checkout is clean")
    summary = workflow.index("- name: Manual private release required")
    assert resolve < ci_gate < posture < clean < summary
    assert "deployment performed: **no**" in workflow
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
    assert "python scripts/railway_preflight.py --db --strict" in sop
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
    manifest_gate = private_release.index(
        "python3 scripts/railway_preflight.py --manifest-only"
    )
    current_gate = private_release.index(
        'python3 scripts/railway_preflight.py --live --strict --url "$API_URL"'
    )
    source_gate = private_release.index(
        "python3 scripts/railway_preflight.py --railway-source-unbound"
    )
    assert '--railway-project "$PROJECT_ID"' in private_release
    assert '--railway-environment "$ENVIRONMENT"' in private_release
    assert '--railway-service "$SERVICE"' in private_release
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
    assert (
        manifest_gate
        < current_gate
        < source_gate
        < release_context
        < deploy
        < post_gate
    )
    assert "`railway run` executes locally" in sop


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
    assert 'PROJECT_ID="${PROJECT_ID:?set PROJECT_ID' in canonical
    source_gate = canonical.index(
        "python3 scripts/railway_preflight.py --railway-source-unbound"
    )
    assert '--railway-project "$PROJECT_ID"' in canonical
    assert "--railway-environment production" in canonical
    assert "--railway-service api-service" in canonical
    canonical_prepare = canonical.index(
        'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"'
    )
    canonical_deploy = canonical.index('railway up "$RELEASE_CONTEXT"')
    assert '--project "$PROJECT_ID"' in canonical[canonical_deploy:]
    assert (
        canonical.index("set -euo pipefail")
        < source_gate
        < canonical_prepare
        < canonical_deploy
    )


def test_customer_restore_sop_does_not_misstate_volume_restore_semantics() -> None:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    normalized = " ".join(sop.split())

    assert "Prefer a Railway PITR restore" in normalized
    assert "ordinary Railway volume-backup restore instead swaps" in normalized
    assert "removes backups newer than the selected point" in normalized
    assert "restored disposable target" not in sop


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


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

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _Response(payload))


def _patch_endpoint_get(monkeypatch, dependencies_payload, liveness_payload):
    import httpx

    def get(url, **_kwargs):
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
        approved_public_url=None,
    ):
        seen.append(
            (
                url,
                expected_version,
                expected_commit_sha,
                expected_signing_key_id,
                expected_signing_public_key_sha256,
                approved_public_url,
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
            "https://api.example.com",
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


def test_public_dns_resolution_accepts_global_ipv4_and_ipv6(monkeypatch):
    records = [
        _dns_answer("93.184.216.34"),
        _dns_answer("2606:2800:220:1:248:1893:25c8:1946"),
    ]
    seen = []

    def getaddrinfo(host, port, **kwargs):
        seen.append((host, port, kwargs))
        return records

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    assert preflight._resolve_global_hostname("api.example.com") == "93.184.216.34"
    assert seen == [
        (
            "api.example.com",
            443,
            {
                "family": socket.AF_UNSPEC,
                "type": socket.SOCK_STREAM,
                "proto": socket.IPPROTO_TCP,
            },
        )
    ]


def test_public_dns_resolution_accepts_global_ipv6_only(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            _dns_answer("2606:4700:4700::1111"),
        ],
    )

    assert (
        preflight._resolve_global_hostname("ipv6.example.com") == "2606:4700:4700::1111"
    )


@pytest.mark.parametrize(
    "records",
    [
        [],
        [_dns_answer("93.184.216.34"), _dns_answer("10.0.0.7")],
        [_dns_answer("fe80::1")],
        [
            _dns_answer("2606:4700:4700::1111"),
            _dns_answer("::1"),
        ],
        [_dns_answer("224.0.0.1")],
        [_dns_answer("ff02::1")],
        [(socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("ignored", 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ())],
        [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2606:4700:4700::1111", 443),
            )
        ],
        [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", 443, 0, 0),
            )
        ],
    ],
    ids=[
        "no_answers",
        "mixed_public_private",
        "link_local_ipv6",
        "mixed_global_ipv6_loopback",
        "multicast_ipv4",
        "multicast_ipv6",
        "unsupported_family",
        "malformed_socket_address",
        "ipv4_family_with_ipv6_address",
        "ipv6_family_with_ipv4_address",
    ],
)
def test_public_dns_resolution_rejects_unsafe_or_malformed_answers(
    monkeypatch,
    records,
):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: records,
    )

    assert preflight._resolve_global_hostname("api.example.com") is None


def test_public_dns_resolution_fails_closed_on_resolver_error(monkeypatch):
    def getaddrinfo(*_args, **_kwargs):
        raise socket.gaierror("resolver unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    assert preflight._resolve_global_hostname("api.example.com") is None


def test_authenticated_discovery_pins_address_and_preserves_host_and_sni():
    import httpx

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"mcp_tools": []})

    body = preflight._fetch_authenticated_discovery(
        "https://api.example.com",
        "2606:4700:4700::1111",
        "operator-test-key",
        transport=httpx.MockTransport(handler),
    )

    assert body == {"mcp_tools": []}
    assert len(captured) == 1
    request = captured[0]
    assert request.url == httpx.URL("https://[2606:4700:4700::1111]/v1/discover")
    assert request.headers["Host"] == "api.example.com"
    assert request.headers["X-API-Key"] == "operator-test-key"
    assert request.extensions["sni_hostname"] == "api.example.com"


def test_authenticated_discovery_rejects_redirect_without_following_it():
    import httpx

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://attacker.example/v1/discover"},
        )

    with pytest.raises(RuntimeError, match="redirect"):
        preflight._fetch_authenticated_discovery(
            "https://api.example.com",
            "93.184.216.34",
            "operator-test-key",
            transport=httpx.MockTransport(handler),
        )

    assert len(captured) == 1


def test_live_resolves_once_and_uses_the_validated_address(monkeypatch):
    import httpx

    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    resolver_calls = 0
    fetch_calls = []
    monkeypatch.setenv("BOOTSTRAP_KEY", "operator-test-key")
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")

    def getaddrinfo(*_args, **_kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls == 1:
            return [_dns_answer("93.184.216.34")]
        return [_dns_answer("127.0.0.1")]

    def get(url, **_kwargs):
        if url.endswith("/v1/discover"):
            pytest.fail("discovery must use the pinned transport")
        return _Response(payload)

    def fetch(origin, pinned_address, bootstrap_key, **_kwargs):
        fetch_calls.append((origin, pinned_address, bootstrap_key))
        return {"mcp_tools": []}

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        preflight,
        "_fetch_authenticated_discovery",
        fetch,
        raising=False,
    )

    assert preflight.check_live("https://api.example.com") is True
    assert resolver_calls == 1
    assert fetch_calls == [
        ("https://api.example.com", "93.184.216.34", "operator-test-key")
    ]


def _patch_get_with_discovery(monkeypatch, payload, discovery_payload):
    import httpx

    calls = []
    monkeypatch.setenv("BOOTSTRAP_KEY", "operator-test-key")
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/v1/discover"):
            return _Response(discovery_payload)
        return _Response(payload)

    def fetch(origin, pinned_address, bootstrap_key, **_kwargs):
        assert pinned_address == "93.184.216.34"
        calls.append(
            (
                f"{origin}/v1/discover",
                {"headers": {"X-API-Key": bootstrap_key}, "timeout": 30},
            )
        )
        return discovery_payload

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        preflight,
        "_fetch_authenticated_discovery",
        fetch,
        raising=False,
    )
    return calls


def test_live_passes_when_dogfood_flag_absent_and_discovery_clean(monkeypatch):
    """The public projection stopped publishing the flag; a clean /v1/discover
    (no dogfood tools) is the replacement evidence."""
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    calls = _patch_get_with_discovery(
        monkeypatch,
        payload,
        {"mcp_tools": [{"service_id": "partner.echo", "name": "partner.echo"}]},
    )

    assert preflight.check_live("https://api.example.com") is True
    assert calls == [
        ("https://api.example.com/health/dependencies", {"timeout": 30}),
        (
            "https://api.example.com/v1/discover",
            {"headers": {"X-API-Key": "operator-test-key"}, "timeout": 30},
        ),
    ]


def test_live_fails_closed_without_operator_credential(monkeypatch, capsys):
    import httpx

    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    calls = []
    monkeypatch.delenv("BOOTSTRAP_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(payload)

    monkeypatch.setattr(httpx, "get", get)

    assert preflight.check_live("https://api.example.com") is False
    assert calls == [("https://api.example.com/health/dependencies", {"timeout": 30})]
    assert "BOOTSTRAP_KEY is required" in capsys.readouterr().out


def test_live_hides_rejected_operator_credential(monkeypatch, capsys):
    import httpx

    secret = "operator-secret-token-shaped-value"
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    monkeypatch.setenv("BOOTSTRAP_KEY", secret)
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")

    class _RejectedResponse:
        def raise_for_status(self):
            raise RuntimeError(f"rejected credential {secret}")

    def get(url, **kwargs):
        if url.endswith("/v1/discover"):
            assert kwargs["headers"] == {"X-API-Key": secret}
            return _RejectedResponse()
        return _Response(payload)

    def fetch(_origin, _pinned_address, bootstrap_key, **_kwargs):
        assert bootstrap_key == secret
        raise RuntimeError(f"rejected credential {secret}")

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        preflight,
        "_fetch_authenticated_discovery",
        fetch,
        raising=False,
    )

    assert preflight.check_live("https://api.example.com") is False
    output = capsys.readouterr().out
    assert "authenticated /v1/discover could not be checked" in output
    assert secret not in output


@pytest.mark.parametrize(
    ("target_url", "approved_url"),
    [
        ("http://api.example.com", "https://api.example.com"),
        ("https://untrusted.example.com", "https://api.example.com"),
        (
            "https://api.example.com@untrusted.example.com",
            "https://api.example.com",
        ),
        ("https://127.0.0.1", "https://127.0.0.1"),
        ("https://127.1", "https://127.1"),
        ("https://foo.local", "https://foo.local"),
        ("https://foo.localdomain", "https://foo.localdomain"),
        ("https://foo.localhost", "https://foo.localhost"),
        ("https://foo.internal", "https://foo.internal"),
        ("https://foo.home.arpa", "https://foo.home.arpa"),
        ("https://127.0.0.1.nip.io", "https://127.0.0.1.nip.io"),
        ("https://api.example.com/catalog", "https://api.example.com/catalog"),
        (
            "https://api.example.com?target=other",
            "https://api.example.com?target=other",
        ),
    ],
)
def test_live_never_sends_operator_credential_to_unapproved_origin(
    monkeypatch,
    capsys,
    target_url,
    approved_url,
):
    import httpx

    secret = "operator-secret-token-shaped-value"
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    calls = []
    monkeypatch.setenv("BOOTSTRAP_KEY", secret)
    monkeypatch.setenv("PUBLIC_URL", approved_url)

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/v1/discover"):
            return _Response(
                {"mcp_tools": [{"service_id": "partner.echo", "name": "partner.echo"}]}
            )
        return _Response(payload)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        preflight,
        "_fetch_authenticated_discovery",
        lambda *_args, **_kwargs: pytest.fail("authenticated discovery must not run"),
        raising=False,
    )

    assert preflight.check_live(target_url) is False
    assert calls == [(f"{target_url}/health/dependencies", {"timeout": 30})]
    output = capsys.readouterr().out
    assert "approved canonical HTTPS origin" in output
    assert secret not in output


def test_live_rejects_private_dns_before_reading_operator_credential(
    monkeypatch,
    capsys,
):
    import httpx

    target_url = "https://127.0.0.1.nip.io"
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    calls = []
    monkeypatch.setenv("PUBLIC_URL", target_url)
    original_getenv = preflight.os.getenv

    def getenv(name, default=None):
        if name == "BOOTSTRAP_KEY":
            pytest.fail("BOOTSTRAP_KEY must not be read for an unsafe origin")
        return original_getenv(name, default)

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(payload)

    monkeypatch.setattr(preflight.os, "getenv", getenv)
    monkeypatch.setattr(httpx, "get", get)

    assert preflight.check_live(target_url) is False
    assert calls == [(f"{target_url}/health/dependencies", {"timeout": 30})]
    assert "approved canonical HTTPS origin" in capsys.readouterr().out


@pytest.mark.parametrize(
    "discovery_payload",
    [
        ["not", "a", "dict"],
        {},
        {"mcp_tools": "partner.echo"},
        {"mcp_tools": ["partner.notes.write"]},
        {"tools": [{"service_id": "partner.echo"}]},
    ],
)
def test_live_fails_when_discovery_shape_is_unrecognized(
    monkeypatch, discovery_payload
):
    """An unrecognized /v1/discover shape must fail closed, never read as
    "no dogfood tools"."""
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    _patch_get_with_discovery(monkeypatch, payload, discovery_payload)

    assert preflight.check_live("https://api.example.com") is False


def test_live_fails_when_dogfood_tool_exposed_in_discovery(monkeypatch):
    import httpx

    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    monkeypatch.setenv("BOOTSTRAP_KEY", "operator-test-key")
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")

    def get(url, **_kwargs):
        if url.endswith("/v1/discover"):
            return _Response(
                {
                    "mcp_tools": [
                        {
                            "service_id": "partner.notes.write",
                            "name": "partner.notes.write",
                        }
                    ]
                }
            )
        return _Response(payload)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        preflight,
        "_fetch_authenticated_discovery",
        lambda *_args, **_kwargs: {
            "mcp_tools": [
                {
                    "service_id": "partner.notes.write",
                    "name": "partner.notes.write",
                }
            ]
        },
        raising=False,
    )

    assert preflight.check_live("https://api.example.com") is False


def test_live_fails_when_dogfood_flag_absent_and_discovery_unreachable(monkeypatch):
    import httpx

    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    monkeypatch.setenv("BOOTSTRAP_KEY", "operator-test-key")
    monkeypatch.setenv("PUBLIC_URL", "https://api.example.com")

    def get(url, **_kwargs):
        if url.endswith("/v1/discover"):
            raise httpx.ConnectError("boom")
        return _Response(payload)

    def fetch(*_args, **_kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(
        preflight,
        "_fetch_authenticated_discovery",
        fetch,
        raising=False,
    )

    assert preflight.check_live("https://api.example.com") is False


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
    requirement still applies, discovery fallback or not."""
    _patch_get_with_discovery(
        monkeypatch,
        {**HEALTHY, "enable_dogfood_tool": None},
        {"mcp_tools": []},
    )

    assert preflight.check_live("https://api.example.com") is False


def test_live_fails_when_dogfood_name_hides_behind_benign_service_id(monkeypatch):
    """service_id and name are checked independently: a benign service_id
    must not mask a dogfood tool name."""
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    _patch_get_with_discovery(
        monkeypatch,
        payload,
        {"mcp_tools": [{"service_id": "partner.echo", "name": "partner.notes.write"}]},
    )

    assert preflight.check_live("https://api.example.com") is False


@pytest.mark.parametrize(
    "tool",
    [
        {},
        {"service_id": "partner.echo"},
        {"name": "partner.echo"},
        {"service_id": None, "name": "partner.echo"},
        {"service_id": "partner.echo", "name": None},
        {"service_id": "", "name": "partner.echo"},
        {"service_id": "partner.echo", "name": ""},
        {"service_id": " ", "name": "partner.echo"},
        {"service_id": "partner.echo", "name": "\t"},
        {"service_id": ["partner.echo"], "name": "partner.echo"},
        {"service_id": "partner.echo", "name": ["partner.echo"]},
    ],
)
def test_live_fails_on_missing_or_invalid_tool_identifier(
    monkeypatch,
    capsys,
    tool,
):
    """Every catalog entry must carry both non-empty string identifiers."""
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    _patch_get_with_discovery(
        monkeypatch,
        payload,
        {"mcp_tools": [tool]},
    )

    assert preflight.check_live("https://api.example.com") is False
    assert "tool identifiers must be non-empty strings" in capsys.readouterr().out


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
