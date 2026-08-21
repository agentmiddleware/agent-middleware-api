"""
Test that Docker builds stamp the git SHA into the image at build time.

Verifies that `docker build --build-arg COMMIT_SHA=<sha>` results in
/health/dependencies.commit_sha reporting that SHA.
"""

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


def test_dockerfile_declares_commit_sha_arg_and_env():
    """Dockerfile must declare ARG COMMIT_SHA and set BUILD_COMMIT_SHA from it."""
    dockerfile = open("Dockerfile", encoding="utf-8").read()
    assert "ARG COMMIT_SHA" in dockerfile, (
        "Dockerfile must declare ARG COMMIT_SHA for build-time injection"
    )
    assert "BUILD_COMMIT_SHA=${COMMIT_SHA}" in dockerfile, (
        "Dockerfile must set BUILD_COMMIT_SHA from the COMMIT_SHA build arg"
    )


@pytest.mark.anyio
async def test_build_commit_sha_env_appears_in_health(client, monkeypatch):
    """When BUILD_COMMIT_SHA is set, health endpoints must report it."""
    test_sha = "deadbeef1234567890abcdef1234567890abcdef"
    
    monkeypatch.setenv("BUILD_COMMIT_SHA", test_sha)
    get_settings.cache_clear()
    
    liveness = await client.get("/health")
    dependencies = await client.get("/health/dependencies")
    
    assert liveness.status_code == 200
    assert dependencies.status_code == 200
    
    assert liveness.json()["commit_sha"] == test_sha
    assert dependencies.json()["commit_sha"] == test_sha
    
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
