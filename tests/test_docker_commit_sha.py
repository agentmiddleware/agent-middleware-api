"""Test that Docker builds require a staged commit stamp."""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import get_settings
from app.core.build_metadata import get_build_commit_sha


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_dockerfile_requires_staged_commit_sha():
    """The image must fail to build when a release context lacks its stamp."""
    dockerfile = open("Dockerfile", encoding="utf-8").read()
    assert "COPY .build_commit_sha /app/.build_commit_sha" in dockerfile
    assert "ARG COMMIT_SHA" not in dockerfile
    assert "BUILD_COMMIT_SHA=${COMMIT_SHA}" not in dockerfile


def test_local_compose_uses_the_unstamped_development_dockerfile():
    compose = open("docker-compose.yml", encoding="utf-8").read()
    development_dockerfile = open("Dockerfile.dev", encoding="utf-8").read()

    assert "dockerfile: Dockerfile.dev" in compose
    assert ".build_commit_sha" not in development_dockerfile


def test_docker_publish_stages_the_checked_out_commit():
    workflow = open(".github/workflows/docker-publish.yml", encoding="utf-8").read()

    assert 'printf \'%s\\n\' "${{ github.sha }}" > .build_commit_sha' in workflow


@pytest.mark.anyio
async def test_build_commit_sha_env_ignored_without_railway_or_file(client, monkeypatch):
    """BUILD_COMMIT_SHA env is ignored (returns null) to prevent stale service vars."""
    test_sha = "deadbeef1234567890abcdef1234567890abcdef"
    
    monkeypatch.setenv("BUILD_COMMIT_SHA", test_sha)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    get_settings.cache_clear()
    
    liveness = await client.get("/health")
    dependencies = await client.get("/health/dependencies")
    
    assert liveness.status_code == 200
    assert dependencies.status_code == 200
    
    # Must return null, not BUILD_COMMIT_SHA env
    assert liveness.json()["commit_sha"] is None
    assert dependencies.json()["commit_sha"] is None
    
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_build_commit_sha_validation_rejects_malformed(client, monkeypatch):
    """Malformed BUILD_COMMIT_SHA must be rejected (not echoed)."""
    malformed = "not-a-sha; rm -rf /"
    
    monkeypatch.setenv("BUILD_COMMIT_SHA", malformed)
    get_settings.cache_clear()
    
    dependencies = await client.get("/health/dependencies")
    assert dependencies.status_code == 200
    
    assert dependencies.json()["commit_sha"] is None
    assert malformed not in dependencies.text
    
    get_settings.cache_clear()


def test_build_metadata_prefers_railway_over_build_commit_sha(monkeypatch):
    """RAILWAY_GIT_COMMIT_SHA takes precedence over BUILD_COMMIT_SHA."""
    build_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    railway_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    
    get_settings.cache_clear()
    settings = get_settings()
    settings.BUILD_COMMIT_SHA = build_sha
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", railway_sha)
    
    assert get_build_commit_sha() == railway_sha
    
    get_settings.cache_clear()


def test_build_metadata_falls_back_to_railway_when_build_commit_sha_unset(monkeypatch):
    """When BUILD_COMMIT_SHA is empty, fall back to RAILWAY_GIT_COMMIT_SHA."""
    railway_sha = "cccccccccccccccccccccccccccccccccccccccc"
    
    get_settings.cache_clear()
    settings = get_settings()
    settings.BUILD_COMMIT_SHA = ""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", railway_sha)
    
    assert get_build_commit_sha() == railway_sha
    
    get_settings.cache_clear()
