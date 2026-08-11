"""Deploy-gate coverage for scripts/railway_preflight.py.

The preflight only earns its place if it fails on the states that actually
break a Railway deploy: a tree ahead of the deployed schema, a database
bootstrapped by ``create_all`` and never stamped, and a service that came up
with memory state or proof surfaces on.
"""

import asyncio
import importlib.util
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


def test_deploy_workflow_drains_then_rescrubs_and_uses_public_db() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "railway-deploy.yml").read_text()

    inject = workflow.index("- name: Inject build commit SHA")
    deploy = workflow.index("- name: Deploy (railway up)")
    drain = workflow.index("- name: Wait for old workers to drain")
    rescrub = workflow.index("- name: Retire legacy credentials after drain")
    verify = workflow.index("- name: Verify deploy — migrations + posture")
    assert inject < deploy < drain < rescrub < verify
    assert 'BUILD_COMMIT_SHA="$EXPECTED_SHA"' in workflow
    assert "railway variable set" in workflow
    assert "--skip-deploys" in workflow
    assert "python scripts/retire_owner_keys.py" in workflow
    assert "railway run --service Postgres --environment production" in workflow
    assert "--public-db" in workflow
    assert 'activeDeployments[0].status == "SUCCESS"' in workflow
    assert "activeDeployments | length) == 1" in workflow
    assert "python scripts/railway_preflight.py --live --strict" in workflow
    assert '--expected-version "$EXPECTED_VERSION"' in workflow
    assert '--expected-commit-sha "$EXPECTED_SHA"' in workflow


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


EXPECTED_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"


HEALTHY = {
    "status": "healthy",
    "production_like": True,
    "version": "1.3.0",
    "commit_sha": EXPECTED_COMMIT_SHA,
    "unhealthy": [],
    "enable_proof_surfaces": False,
    "enable_dogfood_tool": False,
    "runtime_degradation": {"durable_state": {"fell_back_to_memory": False}},
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


def test_live_fails_when_dogfood_posture_is_missing(monkeypatch):
    payload = {
        key: value for key, value in HEALTHY.items() if key != "enable_dogfood_tool"
    }
    _patch_get(monkeypatch, payload)

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
