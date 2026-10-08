"""Honesty labels for the simulated media and factory proof surfaces.

Covers the GTM-25 slice: simulated hook/clip/distribution outputs must say
so in the API contract, and responses must not advertise download,
thumbnail, or upload URLs that have no route behind them.
"""

import asyncio

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


async def _ready_video_id(client, headers) -> str:
    upload = await client.post(
        "/v1/media/videos",
        json={"title": "Label Check", "source_url": "https://example.com/v.mp4"},
        headers=headers,
    )
    assert upload.status_code == 202, upload.text
    video_id = upload.json()["video_id"]
    for _ in range(100):
        resp = await client.get(f"/v1/media/videos/{video_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        if resp.json()["status"] == "ready":
            return video_id
        await asyncio.sleep(0.01)
    raise AssertionError(f"video {video_id} never reached ready")


@pytest.mark.proof
@pytest.mark.anyio
async def test_media_upload_advertises_no_upload_url(client, api_headers):
    for body in (
        {"title": "No Source", "source_url": "https://example.com/a.mp4"},
        {"title": "Direct Upload Attempt"},
    ):
        resp = await client.post("/v1/media/videos", json=body, headers=api_headers)
        assert resp.status_code == 202, resp.text
        assert resp.json()["upload_url"] is None
        assert "/upload" not in resp.text


@pytest.mark.proof
@pytest.mark.anyio
async def test_media_clips_carry_no_download_or_thumbnail_urls(client, api_headers):
    video_id = await _ready_video_id(client, api_headers)
    resp = await client.post(
        f"/v1/media/videos/{video_id}/clips",
        json={"video_id": video_id, "max_clips": 1},
        headers=api_headers,
    )
    assert resp.status_code == 202, resp.text
    clips = resp.json()["clips"]
    assert clips
    for clip in clips:
        assert clip["download_url"] is None
        assert clip["thumbnail_url"] is None
    assert "/download" not in resp.text
    assert "/thumbnail" not in resp.text


@pytest.mark.proof
@pytest.mark.anyio
async def test_media_hooks_endpoint_says_simulated(client):
    spec = (await client.get("/openapi.json")).json()
    desc = spec["paths"]["/v1/media/videos/{video_id}/hooks"]["get"]["description"]
    assert "simulated" in desc.lower()
    hook_schema = spec["components"]["schemas"]["ViralHook"]
    assert "simulated" in hook_schema["description"].lower()


@pytest.mark.proof
@pytest.mark.anyio
async def test_dead_media_and_factory_paths_have_no_route(client, api_headers):
    video_id = await _ready_video_id(client, api_headers)
    assert (await client.get("/v1/media/videos/anything/upload")).status_code == 404
    assert (
        await client.put(f"/v1/media/videos/{video_id}/upload", headers=api_headers)
    ).status_code in (404, 405)
    assert (
        await client.get("/v1/media/clips/anything/download", headers=api_headers)
    ).status_code == 404
    assert (
        await client.get("/v1/media/clips/anything/thumbnail", headers=api_headers)
    ).status_code == 404
    assert (
        await client.get("/v1/factory/content/anything/download", headers=api_headers)
    ).status_code == 404
    assert (
        await client.get("/v1/factory/content/anything/thumbnail", headers=api_headers)
    ).status_code == 404


@pytest.mark.proof
@pytest.mark.anyio
async def test_factory_pieces_carry_no_dead_urls(client, api_headers):
    create = await client.post(
        "/v1/factory/pipelines",
        json={"title": "Dead URL Check", "target_formats": ["email_snippet"]},
        headers=api_headers,
    )
    assert create.status_code == 202, create.text
    pipeline_id = create.json()["pipeline_id"]
    await asyncio.sleep(0.2)
    resp = await client.get(
        f"/v1/factory/pipelines/{pipeline_id}/content", headers=api_headers
    )
    assert resp.status_code == 200, resp.text
    pieces = resp.json()["content"]
    assert pieces
    for piece in pieces:
        assert piece["download_url"] == ""
        assert piece["thumbnail_url"] is None
    assert "/download" not in resp.text
    assert "/thumbnail" not in resp.text


@pytest.mark.proof
@pytest.mark.anyio
async def test_factory_and_ai_contracts_say_simulated(client):
    spec = (await client.get("/openapi.json")).json()
    paths = spec["paths"]
    for path in (
        "/v1/factory/pipelines",
        "/v1/factory/campaigns",
        "/v1/factory/schedule",
        "/v1/factory/analytics",
    ):
        op = next(iter(paths[path].values()))
        text = f"{op.get('summary', '')} {op.get('description', '')}".lower()
        assert "simulat" in text or "metadata" in text or "fixed default" in text, path
    decide_desc = paths["/v1/ai/decide"]["post"].get("description", "").lower()
    assert "helper" in decide_desc or "ungrounded" in decide_desc
    piece_schema = spec["components"]["schemas"]["GeneratedContent"]
    assert piece_schema["properties"]["download_url"]["description"] != ""
    assert "empty" in piece_schema["properties"]["download_url"]["description"].lower()
