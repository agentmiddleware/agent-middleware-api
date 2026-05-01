"""
Tests for the Programmatic Media Engine endpoints.
Validates video upload, hook detection, clip generation, and distribution.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


# --- Video Upload ---

@pytest.mark.anyio
async def test_upload_video_with_url(client, api_headers):
    resp = await client.post(
        "/v1/media/videos",
        json={
            "source_url": "https://storage.example.com/demo.mp4",
            "title": "Test Video",
            "language": "en",
        },
        headers=api_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "video_id" in data
    assert data["status"] == "processing"
    assert data["upload_url"] is None  # URL provided, no upload needed


@pytest.mark.anyio
async def test_upload_video_without_url(client, api_headers):
    resp = await client.post(
        "/v1/media/videos",
        json={"title": "Direct Upload"},
        headers=api_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "awaiting_upload"
    assert data["upload_url"] is not None


@pytest.mark.anyio
async def test_get_video_status(client, api_headers):
    upload = await client.post(
        "/v1/media/videos",
        json={"title": "Status Check", "source_url": "https://example.com/v.mp4"},
        headers=api_headers,
    )
    video_id = upload.json()["video_id"]

    resp = await client.get(f"/v1/media/videos/{video_id}", headers=api_headers)
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_video_not_found(client, api_headers):
    resp = await client.get("/v1/media/videos/nonexistent", headers=api_headers)
    assert resp.status_code == 404


# --- Hooks ---

@pytest.mark.anyio
async def test_hooks_empty_for_new_video(client, api_headers):
    upload = await client.post(
        "/v1/media/videos",
        json={"title": "Hook Test", "source_url": "https://example.com/v.mp4"},
        headers=api_headers,
    )
    video_id = upload.json()["video_id"]
    resp = await client.get(f"/v1/media/videos/{video_id}/hooks", headers=api_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- Distribution ---

@pytest.mark.anyio
async def test_distribute_nonexistent_clips(client, api_headers):
    resp = await client.post(
        "/v1/media/distribute",
        json={
            "clip_ids": ["fake-clip-1"],
            "platforms": ["youtube_shorts"],
            "title": "Test Post",
        },
        headers=api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_failed"] >= 1


# --- Clip Not Found ---

@pytest.mark.anyio
async def test_clip_not_found(client, api_headers):
    resp = await client.get("/v1/media/clips/nonexistent", headers=api_headers)
    assert resp.status_code == 404
