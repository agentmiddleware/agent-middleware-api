"""Service-level tests for app.services.media_engine.

Covers VideoStore, HookDetector, ClipRenderer, PlatformDistributor,
SchedulingEngine, and the MediaEngine orchestrator directly (no HTTP,
no network, no real platform APIs).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.schemas.media import AspectRatio, CaptionStyle, Platform, ViralHook
from app.services.media_engine import (
    ClipRenderer,
    HookDetector,
    MediaEngine,
    PlatformDistributor,
    SchedulingEngine,
    StoredVideo,
    VideoStatus,
    VideoStore,
)

pytestmark = pytest.mark.proof


def _make_video(**kwargs) -> StoredVideo:
    defaults = {
        "video_id": "vid-1",
        "title": "Test video",
        "source_url": None,
        "language": "en",
        "status": VideoStatus.READY,
        "metadata": {},
        "created_at": datetime.now(timezone.utc),
        "transcript": "A placeholder transcript with enough words.",
        "duration_seconds": 300.0,
    }
    defaults.update(kwargs)
    return StoredVideo(**defaults)


def _make_hook(hook_id="hook-1", start=10.0, end=40.0, confidence=0.8) -> ViralHook:
    return ViralHook(
        hook_id=hook_id,
        start_time_seconds=start,
        end_time_seconds=end,
        confidence_score=confidence,
        trigger_type="emotional_peak",
        transcript_snippet="Speaker reaches an emotional climax",
    )


# --- VideoStore ---


@pytest.mark.anyio
async def test_video_store_create_get_and_status_update():
    store = VideoStore()
    video = _make_video()
    await store.create(video)
    assert await store.get("vid-1") is video
    await store.update_status("vid-1", VideoStatus.ANALYZING)
    assert (await store.get("vid-1")).status == VideoStatus.ANALYZING


@pytest.mark.anyio
async def test_video_store_missing_video_returns_none_and_ignores_update():
    store = VideoStore()
    assert await store.get("does-not-exist") is None
    await store.update_status("does-not-exist", VideoStatus.FAILED)


# --- HookDetector ---


@pytest.mark.anyio
async def test_detect_hooks_returns_ranked_hooks_stored_on_video():
    detector = HookDetector()
    video = _make_video()
    hooks = await detector.detect_hooks(video)
    assert 3 <= len(hooks) <= 5
    scores = [h.confidence_score for h in hooks]
    assert scores == sorted(scores, reverse=True)
    for hook in hooks:
        assert 0.0 <= hook.confidence_score <= 1.0
        assert hook.end_time_seconds > hook.start_time_seconds
        assert hook.start_time_seconds >= 0
    assert video.hooks == hooks


@pytest.mark.anyio
async def test_detect_hooks_without_transcript_still_returns_hooks():
    detector = HookDetector()
    video = _make_video(transcript=None)
    hooks = await detector.detect_hooks(video)
    assert 3 <= len(hooks) <= 5


@pytest.mark.anyio
async def test_detect_hooks_requires_simulation_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "SIMULATION_MODE_MEDIA_ENGINE", False)
    detector = HookDetector()
    with pytest.raises(NotImplementedError):
        await detector.detect_hooks(_make_video())


# --- ClipRenderer ---


@pytest.mark.anyio
async def test_render_clip_derives_duration_and_urls():
    renderer = ClipRenderer()
    video = _make_video()
    hook = _make_hook(start=10.0, end=40.0)
    clip = await renderer.render_clip(
        video, hook, AspectRatio.PORTRAIT_9_16, CaptionStyle.KARAOKE
    )
    assert clip.video_id == video.video_id
    assert clip.hook_id == hook.hook_id
    assert clip.duration_seconds == pytest.approx(30.0)
    assert clip.aspect_ratio == AspectRatio.PORTRAIT_9_16
    assert clip.caption_style == CaptionStyle.KARAOKE
    assert clip.clip_id in clip.download_url
    assert clip.clip_id in (clip.thumbnail_url or "")


@pytest.mark.anyio
async def test_render_batch_fans_out_hooks_by_aspect_ratio():
    renderer = ClipRenderer()
    video = _make_video()
    hooks = [_make_hook(f"hook-{i}", confidence=0.9 - i * 0.1) for i in range(3)]
    clips = await renderer.render_batch(
        video,
        hooks,
        [AspectRatio.PORTRAIT_9_16, AspectRatio.SQUARE_1_1],
        CaptionStyle.WORD_BY_WORD,
        max_clips=2,
    )
    assert len(clips) == 4
    assert {c.hook_id for c in clips} == {"hook-0", "hook-1"}
    assert {c.aspect_ratio for c in clips} == {
        AspectRatio.PORTRAIT_9_16,
        AspectRatio.SQUARE_1_1,
    }


@pytest.mark.anyio
async def test_render_batch_with_no_hooks_returns_empty():
    renderer = ClipRenderer()
    clips = await renderer.render_batch(
        _make_video(), [], [AspectRatio.PORTRAIT_9_16], CaptionStyle.WORD_BY_WORD
    )
    assert clips == []


# --- PlatformDistributor ---


@pytest.mark.anyio
async def test_distribute_marks_immediate_and_scheduled_posts():
    distributor = PlatformDistributor()
    engine = MediaEngine()
    video = await engine.ingest_video(title="Dist t")
    video.hooks = [_make_hook()]
    clips = await engine.generate_clips(video.video_id)
    clip = clips[0]

    immediate = await distributor.distribute(
        clip, Platform.YOUTUBE_SHORTS, title="t", hashtags=["demo"]
    )
    assert immediate.status == "simulated"
    assert immediate.platform_post_id
    assert immediate.platform_url
    assert "youtube.com/shorts/" in immediate.platform_url

    when = datetime.now(timezone.utc) + timedelta(hours=2)
    scheduled = await distributor.distribute(
        clip, Platform.TIKTOK, title="t", hashtags=[], schedule_at=when
    )
    assert scheduled.status == "simulated_scheduled"
    assert scheduled.scheduled_at == when
    assert "tiktok.com/" in (scheduled.platform_url or "")


@pytest.mark.anyio
async def test_distribute_requires_simulation_mode(monkeypatch):
    import uuid

    from app.schemas.media import GeneratedClip

    monkeypatch.setattr(get_settings(), "SIMULATION_MODE_MEDIA_ENGINE", False)
    distributor = PlatformDistributor()
    clip = GeneratedClip(
        clip_id=str(uuid.uuid4()),
        video_id="vid-1",
        hook_id="hook-1",
        aspect_ratio=AspectRatio.PORTRAIT_9_16,
        duration_seconds=30.0,
        download_url="/v1/media/clips/x/download",
        caption_style=CaptionStyle.WORD_BY_WORD,
        generated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(NotImplementedError):
        await distributor.distribute(clip, Platform.X_VIDEO, title="t", hashtags=[])


# --- SchedulingEngine ---


@pytest.mark.anyio
async def test_optimal_time_picks_next_window_today():
    scheduler = SchedulingEngine()
    after = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    result = await scheduler.get_optimal_time(Platform.YOUTUBE_SHORTS, after=after)
    assert result == datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_optimal_time_rolls_to_tomorrow_after_last_window():
    scheduler = SchedulingEngine()
    after = datetime(2026, 1, 5, 21, 30, tzinfo=timezone.utc)
    result = await scheduler.get_optimal_time(Platform.YOUTUBE_SHORTS, after=after)
    assert result == datetime(2026, 1, 6, 14, 0, tzinfo=timezone.utc)


# --- MediaEngine orchestrator ---


@pytest.mark.anyio
async def test_ingest_without_url_awaits_upload():
    engine = MediaEngine()
    video = await engine.ingest_video(title="Direct upload")
    assert video.status == VideoStatus.AWAITING_UPLOAD
    assert await engine.video_store.get(video.video_id) is video


@pytest.mark.anyio
async def test_generate_clips_unknown_video_raises():
    engine = MediaEngine()
    with pytest.raises(ValueError, match="not found"):
        await engine.generate_clips("does-not-exist")


@pytest.mark.anyio
async def test_generate_clips_filters_hooks_and_records_owner():
    engine = MediaEngine()
    video = await engine.ingest_video(title="Clip src", owner_wallet_id="wallet-a")
    video.hooks = [
        _make_hook("keep", confidence=0.9),
        _make_hook("drop", confidence=0.5),
    ]
    clips = await engine.generate_clips(video.video_id, hook_ids=["keep"], max_clips=5)
    assert len(clips) == 1
    assert clips[0].hook_id == "keep"
    assert await engine.get_clip(clips[0].clip_id) == clips[0]
    assert await engine.get_clip_owner(clips[0].clip_id) == "wallet-a"


@pytest.mark.anyio
async def test_distribute_clips_reports_unknown_clip_per_platform():
    engine = MediaEngine()
    results = await engine.distribute_clips(
        ["missing-clip"],
        [Platform.YOUTUBE_SHORTS, Platform.TIKTOK],
        title="t",
        owner_allowed=lambda owner: True,
    )
    assert len(results) == 2
    for result in results:
        assert result.status == "failed"
        assert result.platform_post_id is None
        assert result.platform_url is None
        assert "not found" in (result.error or "")


@pytest.mark.anyio
async def test_distribute_clips_denied_owner_reads_like_unknown_clip():
    engine = MediaEngine()
    video = await engine.ingest_video(title="Owned", owner_wallet_id="wallet-a")
    video.hooks = [_make_hook()]
    clips = await engine.generate_clips(video.video_id)
    results = await engine.distribute_clips(
        [clips[0].clip_id],
        [Platform.YOUTUBE_SHORTS],
        title="t",
        owner_allowed=lambda owner: False,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].platform_post_id is None
    assert "not found" in (results[0].error or "")


@pytest.mark.anyio
async def test_distribute_clips_allowed_owner_succeeds():
    engine = MediaEngine()
    video = await engine.ingest_video(title="Owned", owner_wallet_id="wallet-a")
    video.hooks = [_make_hook()]
    clips = await engine.generate_clips(video.video_id)
    results = await engine.distribute_clips(
        [clips[0].clip_id],
        [Platform.YOUTUBE_SHORTS],
        title="t",
        schedule_at=None,
        optimize_schedule=False,
        owner_allowed=lambda owner: owner == "wallet-a",
    )
    assert len(results) == 1
    assert results[0].status == "simulated"
    assert results[0].platform_url


@pytest.mark.anyio
async def test_get_clip_missing_returns_none():
    engine = MediaEngine()
    assert await engine.get_clip("does-not-exist") is None
    assert await engine.get_clip_owner("does-not-exist") is None
