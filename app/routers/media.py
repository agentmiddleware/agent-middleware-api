"""
Programmatic Media Engine Router
---------------------------------
Ingest long-form video -> detect viral hooks -> reframe for vertical ->
generate animated captions -> distribute to platforms via API.

Wired to MediaEngine service via FastAPI dependency injection.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core.auth import verify_api_key
from ..core.dependencies import get_media_engine
from ..services.media_engine import MediaEngine
from ..schemas.media import (
    VideoUploadRequest,
    VideoUploadResponse,
    ViralHook,
    ClipGenerationRequest,
    ClipGenerationResponse,
    GeneratedClip,
    DistributionRequest,
    DistributionResponse,
)

router = APIRouter(
    prefix="/v1/media",
    tags=["Programmatic Media Engine"],
    dependencies=[Depends(verify_api_key)],
    responses={
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key"},
    },
)


@router.post(
    "/videos",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a video for processing",
    description=(
        "Submit a video for the media engine pipeline. Provide either a "
        "source_url for the engine to fetch, or use the returned upload_url "
        "to push the file directly. Processing begins automatically after upload."
    ),
)
async def upload_video(
    request: VideoUploadRequest,
    engine: MediaEngine = Depends(get_media_engine),
):
    video = await engine.ingest_video(
        title=request.title,
        source_url=request.source_url,
        language=request.language,
        metadata=request.metadata,
    )

    return VideoUploadResponse(
        video_id=video.video_id,
        upload_url=(
            None if request.source_url
            else f"/v1/media/videos/{video.video_id}/upload"
        ),
        status=video.status.value,
        estimated_processing_seconds=120 if request.source_url else None,
    )


@router.get(
    "/videos/{video_id}",
    summary="Get video processing status",
    description="Check the current status of a video in the processing pipeline.",
)
async def get_video_status(
    video_id: str,
    engine: MediaEngine = Depends(get_media_engine),
):
    video = await engine.video_store.get(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "video_not_found",
                "message": f"Video '{video_id}' not found.",
            },
        )
    return {
        "video_id": video.video_id,
        "title": video.title,
        "source_url": video.source_url,
        "language": video.language,
        "status": video.status.value,
        "created_at": video.created_at.isoformat(),
        "duration_seconds": video.duration_seconds,
        "hook_count": len(video.hooks),
    }


@router.get(
    "/videos/{video_id}/hooks",
    response_model=list[ViralHook],
    summary="Get detected viral hooks",
    description=(
        "Retrieve the viral hooks detected in a processed video. "
        "Hooks are ranked by confidence_score. Each hook identifies "
        "a high-engagement moment based on speech patterns, emotional "
        "peaks, visual surprises, or audience retention signals."
    ),
)
async def get_viral_hooks(
    video_id: str,
    min_confidence: float = Query(
        0.0, ge=0.0, le=1.0, description="Minimum confidence threshold"
    ),
    engine: MediaEngine = Depends(get_media_engine),
):
    video = await engine.video_store.get(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "video_not_found"},
        )

    hooks = video.hooks
    if min_confidence > 0:
        hooks = [h for h in hooks if h.confidence_score >= min_confidence]
    return sorted(hooks, key=lambda h: h.confidence_score, reverse=True)


@router.post(
    "/videos/{video_id}/clips",
    response_model=ClipGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate platform-ready clips",
    description=(
        "Generate reframed, captioned clips from detected viral hooks. "
        "Clips are automatically reframed to the target aspect ratio(s) "
        "and overlaid with animated captions in the chosen style. "
        "80%% of social video is consumed muted — captions are not optional."
    ),
)
async def generate_clips(
    video_id: str,
    request: ClipGenerationRequest,
    engine: MediaEngine = Depends(get_media_engine),
):
    try:
        clips = await engine.generate_clips(
            video_id=video_id,
            hook_ids=request.hooks,
            max_clips=request.max_clips,
            aspect_ratios=request.aspect_ratios,
            caption_style=request.caption_style,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "video_not_found", "message": str(e)},
        )

    return ClipGenerationResponse(
        video_id=video_id,
        clips=clips,
        total_generated=len(clips),
        status="completed",
    )


@router.post(
    "/distribute",
    response_model=DistributionResponse,
    summary="Distribute clips to social platforms",
    description=(
        "Push generated clips directly to social platforms via their APIs. "
        "No app is opened. Supports YouTube Shorts, TikTok, Instagram Reels, "
        "X Video, and LinkedIn Video. Set optimize_schedule=true to let the "
        "algorithm pick optimal posting windows based on historical engagement data."
    ),
)
async def distribute_clips(
    request: DistributionRequest,
    engine: MediaEngine = Depends(get_media_engine),
):
    results = await engine.distribute_clips(
        clip_ids=request.clip_ids,
        platforms=request.platforms,
        title=request.title,
        hashtags=request.hashtags,
        schedule_at=request.schedule_at,
        optimize_schedule=request.optimize_schedule,
    )

    published = sum(1 for r in results if r.status in ("published", "scheduled"))
    failed = sum(1 for r in results if r.status == "failed")

    return DistributionResponse(
        results=results,
        total_distributed=published,
        total_failed=failed,
    )


@router.get(
    "/clips/{clip_id}",
    response_model=GeneratedClip,
    summary="Get clip details",
    description="Retrieve metadata and download URL for a generated clip.",
)
async def get_clip(
    clip_id: str,
    engine: MediaEngine = Depends(get_media_engine),
):
    clip = await engine.get_clip(clip_id)
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "clip_not_found"},
        )
    return clip
