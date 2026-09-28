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
    assert "python scripts/railway_preflight.py --db --runtime-posture --strict" in sop
    assert "python scripts/railway_preflight.py --db --strict" not in sop
    assert "PRIVATE_RELEASE_CHECKS_OK" in sop
    assert 'test "$sentinel_count" -eq 1' in sop
    assert 'test "$post_ready" = "true"' in sop
    assert sop.count('--manifest "$MANIFEST" --url "$API_URL"') == 2
    assert 'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"' in private_release
    assert 'railway up "$RELEASE_CONTEXT" --path-as-root' in private_release
    assert 'test "$(cat "$RELEASE_CONTEXT/.build_commit_sha")" = "$DEPLOY_SHA"' in private_release
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
    private_deploy = private_release[deploy : private_release.index(
        "# Resolve and wait for the uniquely marked deployment"
    )]
    assert "--no-gitignore" in private_deploy
    post_gate = private_release.rindex(
        "python3 scripts/railway_preflight.py --live --strict"
    )
    assert source_gate < current_gate < release_context < deploy < post_gate
    assert "`railway run` executes locally" in sop


def test_canonical_railway_sop_uses_immutable_release_context() -> None:
    sop = (REPO_ROOT / "docs" / "deploy-railway.md").read_text()
    canonical = sop[
        sop.index("## Canonical deploy path") : sop.index(
            "## Required production variables"
        )
    ]

    assert 'RELEASE_CONTEXT="$(python3 scripts/prepare_railway_release.py --ref "$DEPLOY_SHA")"' in canonical
    assert "set -euo pipefail" in canonical
    assert 'test -d "$RELEASE_CONTEXT"' in canonical
    assert 'test "$(cat "$RELEASE_CONTEXT/.build_commit_sha")" = "$DEPLOY_SHA"' in canonical
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
def runtime_settings(monkeypatch):
    """Resolve settings from this test's environment only (no .env file)."""
    from app.core import config

    def configure(**environment):
        values = {
            "ENVIRONMENT": "production",
            "ENABLE_DOGFOOD_TOOL": "false",
            "ENABLE_DOGFOOD_SECOND_TOOL": "false",
            **environment,
        }
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(
            config, "get_settings", lambda: config.Settings(_env_file=None)
        )

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


def test_runtime_posture_fails_closed_without_rendering_config_errors(
    monkeypatch,
    capsys,
):
    from app.core import config

    secret = "postgresql://user:runtime-secret@postgres.railway.internal/db"

    def unresolvable():
        raise ValueError(f"invalid DATABASE_URL {secret}")

    monkeypatch.setattr(config, "get_settings", unresolvable)

    assert preflight.check_runtime_posture() is False
    output = capsys.readouterr().out
    assert "unable to resolve the runtime configuration (ValueError)" in output
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
