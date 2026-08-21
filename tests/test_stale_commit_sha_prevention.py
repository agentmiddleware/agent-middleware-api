"""
Test that stale COMMIT_SHA/BUILD_COMMIT_SHA service variables don't win.

After PR #343, RAILWAY_GIT_COMMIT_SHA > BUILD_COMMIT_SHA, but when Railway
doesn't set RAILWAY_GIT_COMMIT_SHA (e.g., on `railway up`), a stale
COMMIT_SHA or BUILD_COMMIT_SHA service variable still wins.

This fix ensures:
- Railway env always wins (when set)
- Baked file (.build_commit_sha) wins over stale runtime env vars
- Stale service variables are ignored when a baked file exists
"""

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.build_metadata import get_build_commit_sha
from app.core.config import get_settings
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_railway_env_wins_over_baked_file(monkeypatch, tmp_path):
    """RAILWAY_GIT_COMMIT_SHA must win over baked file."""
    fresh_railway = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    baked_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    
    # Create a fake baked file
    fake_file = tmp_path / ".build_commit_sha"
    fake_file.write_text(baked_sha)
    
    monkeypatch.setattr("app.core.build_metadata._BUILD_SHA_FILE", fake_file)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", fresh_railway)
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)
    get_settings.cache_clear()
    
    result = get_build_commit_sha()
    assert result == fresh_railway, (
        "RAILWAY_GIT_COMMIT_SHA must win over baked file"
    )
    
    get_settings.cache_clear()


def test_baked_file_wins_over_stale_service_env(monkeypatch, tmp_path):
    """Baked file must win over stale BUILD_COMMIT_SHA service variable."""
    baked_sha = "cccccccccccccccccccccccccccccccccccccccc"
    stale_service_var = "a928fd6f00000000000000000000000000000000"
    
    fake_file = tmp_path / ".build_commit_sha"
    fake_file.write_text(baked_sha)
    
    monkeypatch.setattr("app.core.build_metadata._BUILD_SHA_FILE", fake_file)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("BUILD_COMMIT_SHA", stale_service_var)
    get_settings.cache_clear()
    
    result = get_build_commit_sha()
    assert result == baked_sha, (
        "Baked file must win over stale BUILD_COMMIT_SHA service variable"
    )
    assert result != stale_service_var
    
    get_settings.cache_clear()


def test_returns_none_when_railway_unset_and_no_baked_file_and_stale_var(monkeypatch):
    """When Railway unset, no baked file, but stale var exists, must return None.
    
    This prevents stale COMMIT_SHA/BUILD_COMMIT_SHA service variables from
    winning after railway up without --build-arg.
    """
    stale_var = "a928fd6f00000000000000000000000000000000"
    
    # Point to non-existent file (simulates railway up without --build-arg)
    monkeypatch.setattr(
        "app.core.build_metadata._BUILD_SHA_FILE",
        Path("/nonexistent/.build_commit_sha")
    )
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("BUILD_COMMIT_SHA", stale_var)
    get_settings.cache_clear()
    
    result = get_build_commit_sha()
    # Must return None, not the stale service variable
    assert result is None, (
        "Must return None (not stale BUILD_COMMIT_SHA) when Railway env unset "
        "and no baked file exists"
    )
    
    get_settings.cache_clear()


def test_local_dev_must_set_railway_git_commit_sha_explicitly(monkeypatch):
    """For local dev without Docker, set RAILWAY_GIT_COMMIT_SHA explicitly.
    
    BUILD_COMMIT_SHA env is no longer trusted to prevent stale service variables.
    """
    local_sha = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    
    monkeypatch.setattr(
        "app.core.build_metadata._BUILD_SHA_FILE",
        Path("/nonexistent/.build_commit_sha")
    )
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", local_sha)
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)
    get_settings.cache_clear()
    
    result = get_build_commit_sha()
    assert result == local_sha, (
        "Local dev should set RAILWAY_GIT_COMMIT_SHA explicitly"
    )
    
    get_settings.cache_clear()


def test_returns_none_when_all_sources_unavailable(monkeypatch):
    """Return None when Railway unset, no baked file, and no BUILD_COMMIT_SHA."""
    monkeypatch.setattr(
        "app.core.build_metadata._BUILD_SHA_FILE",
        Path("/nonexistent/.build_commit_sha")
    )
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("BUILD_COMMIT_SHA", "")
    get_settings.cache_clear()
    
    result = get_build_commit_sha()
    assert result is None
    
    get_settings.cache_clear()


def test_invalid_baked_file_content_returns_none(monkeypatch, tmp_path):
    """Invalid SHA in baked file returns None (no fallback to BUILD_COMMIT_SHA)."""
    invalid_content = "not-a-valid-sha"
    stale_env = "ffffffffffffffffffffffffffffffffffffffff"
    
    fake_file = tmp_path / ".build_commit_sha"
    fake_file.write_text(invalid_content)
    
    monkeypatch.setattr("app.core.build_metadata._BUILD_SHA_FILE", fake_file)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("BUILD_COMMIT_SHA", stale_env)
    get_settings.cache_clear()
    
    result = get_build_commit_sha()
    # Invalid baked file + no Railway env = None (not BUILD_COMMIT_SHA)
    assert result is None
    
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_health_reports_baked_sha_not_stale_var(client, monkeypatch, tmp_path):
    """Health endpoints must report baked SHA, not stale service variable."""
    baked_sha = "1111111111111111111111111111111111111111"
    stale_var = "a928fd6f00000000000000000000000000000000"
    
    fake_file = tmp_path / ".build_commit_sha"
    fake_file.write_text(baked_sha)
    
    monkeypatch.setattr("app.core.build_metadata._BUILD_SHA_FILE", fake_file)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("BUILD_COMMIT_SHA", stale_var)
    get_settings.cache_clear()
    
    liveness = await client.get("/health")
    dependencies = await client.get("/health/dependencies")
    
    assert liveness.status_code == 200
    assert dependencies.status_code == 200
    
    assert liveness.json()["commit_sha"] == baked_sha
    assert dependencies.json()["commit_sha"] == baked_sha
    
    # Must NOT report the stale variable
    assert stale_var not in liveness.text
    assert stale_var not in dependencies.text
    
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_health_reports_railway_env_when_set(client, monkeypatch, tmp_path):
    """Health must report Railway env even when baked file exists."""
    railway_sha = "2222222222222222222222222222222222222222"
    baked_sha = "3333333333333333333333333333333333333333"
    
    fake_file = tmp_path / ".build_commit_sha"
    fake_file.write_text(baked_sha)
    
    monkeypatch.setattr("app.core.build_metadata._BUILD_SHA_FILE", fake_file)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", railway_sha)
    get_settings.cache_clear()
    
    liveness = await client.get("/health")
    dependencies = await client.get("/health/dependencies")
    
    assert liveness.status_code == 200
    assert dependencies.status_code == 200
    
    assert liveness.json()["commit_sha"] == railway_sha
    assert dependencies.json()["commit_sha"] == railway_sha
    
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_railway_up_without_build_arg_reports_null_not_stale(
    client, monkeypatch
):
    """CTO requirement: railway up without --build-arg must report null, not a928fd6f.
    
    Scenario: railway up (no --build-arg), so no baked file exists.
    Stale COMMIT_SHA/BUILD_COMMIT_SHA service variable exists.
    Railway doesn't set RAILWAY_GIT_COMMIT_SHA.
    
    Expected: health.commit_sha = null (not the stale a928fd6f)
    """
    stale_service_var = "a928fd6f00000000000000000000000000000000"
    
    # No baked file (railway up without --build-arg)
    monkeypatch.setattr(
        "app.core.build_metadata._BUILD_SHA_FILE",
        Path("/nonexistent/.build_commit_sha")
    )
    # Railway doesn't set its env
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    # Stale service variable exists
    monkeypatch.setenv("BUILD_COMMIT_SHA", stale_service_var)
    get_settings.cache_clear()
    
    liveness = await client.get("/health")
    dependencies = await client.get("/health/dependencies")
    
    assert liveness.status_code == 200
    assert dependencies.status_code == 200
    
    # Must return null, NOT the stale SHA
    assert liveness.json()["commit_sha"] is None
    assert dependencies.json()["commit_sha"] is None
    
    # Stale SHA must NOT appear anywhere
    assert stale_service_var not in liveness.text
    assert stale_service_var not in dependencies.text
    assert "a928fd6f" not in liveness.text
    assert "a928fd6f" not in dependencies.text
    
    get_settings.cache_clear()


def test_dockerfile_creates_build_commit_sha_file():
    """Dockerfile must create .build_commit_sha file from COMMIT_SHA arg."""
    # Use relative path from test file location to repo root
    repo_root = Path(__file__).parent.parent
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    
    assert "ARG COMMIT_SHA" in dockerfile
    assert 'echo "$COMMIT_SHA" > /app/.build_commit_sha' in dockerfile or \
           'echo "$COMMIT_SHA"' in dockerfile and '.build_commit_sha' in dockerfile, (
        "Dockerfile must write COMMIT_SHA to .build_commit_sha file"
    )
