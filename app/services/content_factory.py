"""
Programmatic Content Factory — Service Layer
==============================================
Turns a single source asset into a swarm of format-adapted content pieces.

Pipeline: Source → Hook Extraction → Format Adaptation → Render → Schedule → Distribute

Live Mode (Week 6+):
One long-form video becomes:
- 3 targeted hooks × 7 formats each = 21 content pieces
- All rendered in 9:16 vertical with animated captions
- Auto-scheduled across TikTok, YouTube Shorts, Instagram Reels

Production wiring:
- FFmpeg for video/image rendering
- Whisper for transcription
- ML models for key-frame extraction and text summarization
"""

import asyncio
import uuid
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from ..schemas.content_factory import (
    ContentFormat,
    ContentStatus,
    GeneratedContent,
    PlatformAnalytics,
    ScheduleRecommendation,
    ContentHook,
    CaptionStyle,
    CampaignHookResult,
    LiveCampaignResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content Store
# ---------------------------------------------------------------------------

@dataclass
class ContentPipeline:
    """A content generation pipeline instance."""
    pipeline_id: str
    title: str
    source_clip_id: str | None
    source_url: str | None
    target_formats: list[ContentFormat]
    brand_config: dict
    language: str
    auto_schedule: bool
    owner_key: str = ""         # RED TEAM FIX: Tenant scoping
    status: str = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_pieces: list[GeneratedContent] = field(default_factory=list)
    # Live mode fields
    hook: ContentHook | None = None
    caption_style: CaptionStyle = CaptionStyle.BOLD_IMPACT
    aspect_ratio: str = "9:16"


@dataclass
class LiveCampaign:
    """A live content campaign spanning multiple hooks and pipelines."""
    campaign_id: str
    campaign_title: str
    source_url: str
    hooks: list[ContentHook]
    pipeline_ids: list[str] = field(default_factory=list)
    status: str = "running"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    owner_key: str = ""


class ContentStore:
    """In-memory pipeline and content store. Production: PostgreSQL + S3."""

    def __init__(self):
        self._pipelines: dict[str, ContentPipeline] = {}
        self._content: dict[str, GeneratedContent] = {}
        self._campaigns: dict[str, LiveCampaign] = {}
        self._lock = asyncio.Lock()

    async def create_pipeline(self, pipeline: ContentPipeline) -> ContentPipeline:
        async with self._lock:
            self._pipelines[pipeline.pipeline_id] = pipeline
        return pipeline

    async def get_pipeline(self, pipeline_id: str) -> ContentPipeline | None:
        return self._pipelines.get(pipeline_id)

    async def store_content(self, content: GeneratedContent):
        async with self._lock:
            self._content[content.content_id] = content
            pipeline = self._pipelines.get(content.pipeline_id)
            if pipeline:
                pipeline.content_pieces.append(content)

    async def get_content(self, content_id: str) -> GeneratedContent | None:
        return self._content.get(content_id)

    async def list_by_pipeline(self, pipeline_id: str) -> list[GeneratedContent]:
        pipeline = self._pipelines.get(pipeline_id)
        if pipeline:
            return pipeline.content_pieces
        return []

    async def create_campaign(self, campaign: LiveCampaign) -> LiveCampaign:
        async with self._lock:
            self._campaigns[campaign.campaign_id] = campaign
        return campaign

    async def get_campaign(self, campaign_id: str) -> LiveCampaign | None:
        return self._campaigns.get(campaign_id)

    async def list_campaigns(self) -> list[LiveCampaign]:
        return list(self._campaigns.values())


# ---------------------------------------------------------------------------
# Format Adapters (upgraded for Live Mode)
# ---------------------------------------------------------------------------

# 1-to-20 multiplication rule: pieces per format per hook
HOOK_FORMAT_MULTIPLIERS = {
    ContentFormat.SHORT_VIDEO: 3,      # 3 clip variants per hook
    ContentFormat.STATIC_IMAGE: 3,     # 3 thumbnail variants
    ContentFormat.TEXT_POST: 3,         # 3 platform-adapted text posts
    ContentFormat.CAROUSEL: 1,         # 1 deep-dive carousel
    ContentFormat.AUDIOGRAM: 1,        # 1 audio waveform
    ContentFormat.BLOG_EXCERPT: 1,     # 1 SEO excerpt
    ContentFormat.EMAIL_SNIPPET: 1,    # 1 newsletter block
    ContentFormat.QUOTE_CARD: 2,       # 2 pull-quote images
    ContentFormat.DEBATE_CLIP: 1,      # 1 side-by-side debate
    ContentFormat.LONG_VIDEO: 1,       # 1 long-form version
}

# Standard pipeline multipliers (non-hook mode)
FORMAT_MULTIPLIERS = {
    ContentFormat.SHORT_VIDEO: 5,
    ContentFormat.LONG_VIDEO: 1,
    ContentFormat.AUDIOGRAM: 1,
    ContentFormat.CAROUSEL: 2,
    ContentFormat.STATIC_IMAGE: 5,
    ContentFormat.TEXT_POST: 5,
    ContentFormat.BLOG_EXCERPT: 1,
    ContentFormat.EMAIL_SNIPPET: 1,
    ContentFormat.QUOTE_CARD: 2,
    ContentFormat.DEBATE_CLIP: 1,
}

# Caption style configurations
CAPTION_CONFIGS = {
    CaptionStyle.WORD_BY_WORD: {
        "animation": "pop",
        "font_size": 48,
        "position": "center",
        "bg_opacity": 0.7,
    },
    CaptionStyle.SENTENCE_HIGHLIGHT: {
        "animation": "highlight",
        "font_size": 36,
        "position": "bottom_third",
        "bg_opacity": 0.5,
    },
    CaptionStyle.KARAOKE: {
        "animation": "bounce",
        "font_size": 42,
        "position": "center",
        "bg_opacity": 0.6,
    },
    CaptionStyle.BOLD_IMPACT: {
        "animation": "slam",
        "font_size": 64,
        "position": "center",
        "bg_opacity": 0.0,
        "stroke_width": 3,
        "font_weight": "900",
    },
    CaptionStyle.DUAL_COLOR: {
        "animation": "fade_swap",
        "font_size": 48,
        "position": "center",
        "primary_color": "#FFFFFF",
        "accent_color": "#FF6B00",
    },
}


class FormatAdapter:
    """
    Generates content in a specific format from source material.
    Each adapter handles one output format.
    Upgraded for Live Mode: hook-aware metadata, 9:16 vertical, animated captions.
    """

    @staticmethod
    async def adapt_short_video(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate a vertical short-form video clip with animated captions."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook
        caption_config = CAPTION_CONFIGS.get(
            pipeline.caption_style, CAPTION_CONFIGS[CaptionStyle.BOLD_IMPACT]
        )
        dimensions = "1080x1920" if pipeline.aspect_ratio == "9:16" else "1920x1080"

        metadata = {
            "brand_config": pipeline.brand_config,
            "caption_style": pipeline.caption_style.value,
            "caption_config": caption_config,
            "aspect_ratio": pipeline.aspect_ratio,
            "variant": index + 1,
        }
        if hook:
            metadata.update({
                "hook_id": hook.hook_id or "",
                "hook_type": hook.hook_type.value,
                "source_segment": f"{hook.start_seconds}s-{hook.end_seconds}s",
                "transcript_snippet": hook.transcript_snippet[:200],
            })

        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.SHORT_VIDEO,
            title=f"{pipeline.title} — Clip {index + 1}",
            description=(
                f"9:16 vertical clip with {pipeline.caption_style.value} captions. "
                f"Hook: {hook.title if hook else 'auto-detected'}"
            ),
            download_url=f"/v1/factory/content/{content_id}/download",
            thumbnail_url=f"/v1/factory/content/{content_id}/thumbnail",
            duration_seconds=hook.end_seconds - hook.start_seconds if hook else 30.0,
            dimensions=dimensions,
            file_size_bytes=5_000_000,
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata=metadata,
        )

    @staticmethod
    async def adapt_static_image(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate a key-frame thumbnail with text overlay and pull quote."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook

        metadata = {"brand_config": pipeline.brand_config, "variant": index + 1}
        if hook:
            metadata.update(
                {
                    "hook_id": hook.hook_id,
                    "pull_quote": (
                        hook.transcript_snippet[:140] if hook.transcript_snippet else ""
                    ),
                    "talking_points": hook.talking_points[:3],
                }
            )

        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.STATIC_IMAGE,
            title=f"{pipeline.title} — Image {index + 1}",
            description=f"Key-frame with pull quote from '{pipeline.title}'",
            download_url=f"/v1/factory/content/{content_id}/download",
            thumbnail_url=f"/v1/factory/content/{content_id}/download",
            dimensions="1080x1080",
            file_size_bytes=500_000,
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata=metadata,
        )

    @staticmethod
    async def adapt_text_post(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate a platform-native text post with pull quote."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook

        # Platform-specific adaptations
        platforms = ["twitter", "linkedin", "threads"]
        target_platform = platforms[index % len(platforms)]

        talking_points = hook.talking_points if hook else ["Agent economy insight"]
        text = (
            hook.transcript_snippet[:200] if hook and hook.transcript_snippet
            else f"Key insight from {pipeline.title}: [auto-generated pull quote]"
        )

        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.TEXT_POST,
            title=f"{pipeline.title} — {target_platform.title()} Post {index + 1}",
            description=f"Auto-generated {target_platform} post",
            download_url=f"/v1/factory/content/{content_id}/download",
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={
                "text": text,
                "platform": target_platform,
                "hashtags": ["agenteconomy", "b2a", "automation", "aiagents"],
                "talking_points": talking_points,
                "hook_id": hook.hook_id if hook else None,
            },
        )

    @staticmethod
    async def adapt_audiogram(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate audio waveform video for podcast distribution."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook
        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.AUDIOGRAM,
            title=f"{pipeline.title} — Audiogram",
            download_url=f"/v1/factory/content/{content_id}/download",
            duration_seconds=hook.end_seconds - hook.start_seconds if hook else 60.0,
            dimensions="1080x1080",
            file_size_bytes=3_000_000,
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={"hook_id": hook.hook_id if hook else None},
        )

    @staticmethod
    async def adapt_carousel(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate multi-image carousel for Instagram/LinkedIn."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook
        slide_count = max(3, len(hook.talking_points) + 2) if hook else 5

        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.CAROUSEL,
            title=f"{pipeline.title} — Carousel",
            download_url=f"/v1/factory/content/{content_id}/download",
            dimensions="1080x1080",
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={
                "slide_count": slide_count,
                "hook_id": hook.hook_id if hook else None,
                "talking_points": hook.talking_points if hook else [],
            },
        )

    @staticmethod
    async def adapt_blog_excerpt(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate SEO-optimized blog excerpt."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook
        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.BLOG_EXCERPT,
            title=f"{pipeline.title} — Blog Excerpt",
            download_url=f"/v1/factory/content/{content_id}/download",
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={
                "word_count": 250,
                "seo_keywords": [
                    "agent middleware",
                    "b2a",
                    "api automation",
                    "ai agents",
                ],
                "hook_id": hook.hook_id if hook else None,
            },
        )

    @staticmethod
    async def adapt_email_snippet(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate newsletter-ready HTML block."""
        content_id = str(uuid.uuid4())
        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.EMAIL_SNIPPET,
            title=f"{pipeline.title} — Email Block",
            download_url=f"/v1/factory/content/{content_id}/download",
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={"html_preview": "<div>...</div>"},
        )

    @staticmethod
    async def adapt_quote_card(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate a pull-quote image card for debate/reaction sharing."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook
        quote = (
            hook.transcript_snippet[:140] if hook and hook.transcript_snippet
            else f"Key quote from {pipeline.title}"
        )

        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.QUOTE_CARD,
            title=f"{pipeline.title} — Quote Card {index + 1}",
            description=f"Pull-quote card: \"{quote[:60]}...\"",
            download_url=f"/v1/factory/content/{content_id}/download",
            thumbnail_url=f"/v1/factory/content/{content_id}/download",
            dimensions="1080x1080",
            file_size_bytes=400_000,
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={
                "quote": quote,
                "hook_id": hook.hook_id if hook else None,
                "brand_config": pipeline.brand_config,
                "variant": index + 1,
            },
        )

    @staticmethod
    async def adapt_debate_clip(
        pipeline: ContentPipeline,
        index: int,
    ) -> GeneratedContent:
        """Generate a side-by-side debate/contrast clip."""
        content_id = str(uuid.uuid4())
        hook = pipeline.hook
        dimensions = "1080x1920" if pipeline.aspect_ratio == "9:16" else "1920x1080"

        return GeneratedContent(
            content_id=content_id,
            pipeline_id=pipeline.pipeline_id,
            format=ContentFormat.DEBATE_CLIP,
            title=f"{pipeline.title} — Debate Clip",
            description="Side-by-side contrast clip with animated captions",
            download_url=f"/v1/factory/content/{content_id}/download",
            thumbnail_url=f"/v1/factory/content/{content_id}/thumbnail",
            duration_seconds=hook.end_seconds - hook.start_seconds if hook else 45.0,
            dimensions=dimensions,
            file_size_bytes=6_000_000,
            status=ContentStatus.READY,
            generated_at=datetime.now(timezone.utc),
            metadata={
                "hook_id": hook.hook_id if hook else None,
                "caption_style": pipeline.caption_style.value,
                "aspect_ratio": pipeline.aspect_ratio,
                "talking_points": hook.talking_points if hook else [],
            },
        )


FORMAT_ADAPTERS = {
    ContentFormat.SHORT_VIDEO: FormatAdapter.adapt_short_video,
    ContentFormat.STATIC_IMAGE: FormatAdapter.adapt_static_image,
    ContentFormat.TEXT_POST: FormatAdapter.adapt_text_post,
    ContentFormat.AUDIOGRAM: FormatAdapter.adapt_audiogram,
    ContentFormat.CAROUSEL: FormatAdapter.adapt_carousel,
    ContentFormat.BLOG_EXCERPT: FormatAdapter.adapt_blog_excerpt,
    ContentFormat.EMAIL_SNIPPET: FormatAdapter.adapt_email_snippet,
    ContentFormat.QUOTE_CARD: FormatAdapter.adapt_quote_card,
    ContentFormat.DEBATE_CLIP: FormatAdapter.adapt_debate_clip,
}


# ---------------------------------------------------------------------------
# Algorithmic Scheduler
# ---------------------------------------------------------------------------

class AlgorithmicScheduler:
    """
    Learns optimal posting times from engagement analytics.
    Uses a simple historical-peak model: finds the time windows
    that historically produced the highest engagement per platform+format.

    Production: replace with a proper ML model (XGBoost, etc.) trained
    on the analytics data.
    """

    def __init__(self):
        self._analytics: list[PlatformAnalytics] = []
        self._lock = asyncio.Lock()

        # Default engagement curves (hour of day UTC → relative score)
        # Learned from historical data in production
        self._default_curves: dict[str, dict[int, float]] = {
            "youtube_shorts": {9: 0.5, 12: 0.7, 14: 0.8, 17: 1.0, 20: 0.9, 22: 0.6},
            "tiktok": {8: 0.4, 11: 0.7, 15: 0.9, 19: 1.0, 22: 0.8},
            "instagram_reels": {9: 0.5, 12: 0.8, 17: 1.0, 21: 0.9},
            "x_video": {8: 0.6, 13: 0.8, 17: 1.0, 20: 0.7},
            "linkedin_video": {8: 0.9, 10: 1.0, 12: 0.8, 17: 0.7},
        }

    async def ingest_analytics(
        self, metrics: list[PlatformAnalytics]
    ) -> dict[str, int]:
        """Ingest engagement metrics to improve scheduling model."""
        summary: dict[str, int] = defaultdict(int)
        async with self._lock:
            for m in metrics:
                self._analytics.append(m)
                summary[m.platform] += 1
        logger.info(f"Ingested {len(metrics)} analytics data points")
        return dict(summary)

    async def recommend(
        self,
        content_ids: list[str],
        platforms: list[str],
        earliest: datetime | None = None,
        latest: datetime | None = None,
        max_per_day: int = 3,
    ) -> list[ScheduleRecommendation]:
        """
        Generate optimal posting schedule based on engagement data.
        Spreads posts across days to avoid audience fatigue.
        """
        now = datetime.now(timezone.utc)
        start = earliest or now
        end = latest or (now + timedelta(days=7))

        recommendations = []
        # Track posts per platform per day
        slots_used: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for content_id in content_ids:
            for platform in platforms:
                curve = self._default_curves.get(platform, {12: 0.7, 17: 1.0})

                # Find best available slot
                best_slot = await self._find_best_slot(
                    platform, curve, start, end, slots_used[platform], max_per_day
                )

                if best_slot:
                    slot_time, confidence = best_slot
                    day_key = slot_time.strftime("%Y-%m-%d")
                    slots_used[platform][day_key] += 1

                    recommendations.append(ScheduleRecommendation(
                        content_id=content_id,
                        platform=platform,
                        recommended_time=slot_time,
                        confidence=round(confidence, 2),
                        reasoning=self._explain_recommendation(
                            platform, slot_time, confidence
                        ),
                        estimated_views=self._estimate_views(platform, confidence),
                    ))

        # Sort by time
        recommendations.sort(key=lambda r: r.recommended_time)
        return recommendations

    async def _find_best_slot(
        self,
        platform: str,
        curve: dict[int, float],
        start: datetime,
        end: datetime,
        used: dict[str, int],
        max_per_day: int,
    ) -> tuple[datetime, float] | None:
        """Find the highest-engagement available slot."""
        # Sort hours by engagement score (descending)
        ranked_hours = sorted(curve.items(), key=lambda x: x[1], reverse=True)

        current_day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_day <= end:
            day_key = current_day.strftime("%Y-%m-%d")
            if used.get(day_key, 0) >= max_per_day:
                current_day += timedelta(days=1)
                continue

            for hour, score in ranked_hours:
                candidate = current_day.replace(hour=hour)
                if start <= candidate <= end:
                    return candidate, score

            current_day += timedelta(days=1)

        return None

    def _explain_recommendation(
        self, platform: str, time: datetime, confidence: float
    ) -> str:
        """Generate human/agent-readable explanation."""
        day_name = time.strftime("%A")
        hour = time.strftime("%I%p").lstrip("0")
        return (
            f"Historical peak for {platform}: {day_name}s at {hour} UTC "
            f"(confidence: {confidence:.0%}). Based on engagement curve analysis."
        )

    def _estimate_views(self, platform: str, confidence: float) -> int:
        """Rough view estimate based on platform and confidence."""
        base_views = {
            "youtube_shorts": 5000,
            "tiktok": 8000,
            "instagram_reels": 3000,
            "x_video": 2000,
            "linkedin_video": 1500,
        }
        base = base_views.get(platform, 1000)
        return int(base * confidence)

    async def get_analytics_summary(self) -> dict:
        """Return summary of ingested analytics data."""
        by_platform: dict[str, int] = defaultdict(int)
        by_metric: dict[str, int] = defaultdict(int)
        for m in self._analytics:
            by_platform[m.platform] += 1
            by_metric[m.metric_type.value] += 1

        return {
            "total_data_points": len(self._analytics),
            "by_platform": dict(by_platform),
            "by_metric": dict(by_metric),
        }


# ---------------------------------------------------------------------------
# Content Factory Orchestrator
# ---------------------------------------------------------------------------

class ContentFactory:
    """
    Top-level orchestrator for the Programmatic Content Factory.
    Coordinates: source analysis → hook extraction → multi-format adaptation
    → rendering → scheduling → distribution.

    Live Mode: Accepts targeted hooks and applies the 1-to-N multiplication
    rule with 9:16 vertical rendering and animated captions.
    """

    def __init__(self):
        self.store = ContentStore()
        self.scheduler = AlgorithmicScheduler()

    async def create_pipeline(
        self,
        title: str,
        target_formats: list[ContentFormat],
        source_clip_id: str | None = None,
        source_url: str | None = None,
        brand_config: dict | None = None,
        language: str = "en",
        auto_schedule: bool = True,
        owner_key: str = "",
        hook: ContentHook | None = None,
        caption_style: CaptionStyle = CaptionStyle.BOLD_IMPACT,
        aspect_ratio: str = "9:16",
    ) -> ContentPipeline:
        """Create a new content generation pipeline (standard or hook-based)."""
        pipeline = ContentPipeline(
            pipeline_id=str(uuid.uuid4()),
            title=title,
            source_clip_id=source_clip_id,
            source_url=source_url,
            target_formats=target_formats,
            brand_config=brand_config or {},
            language=language,
            auto_schedule=auto_schedule,
            owner_key=owner_key,
            hook=hook,
            caption_style=caption_style,
            aspect_ratio=aspect_ratio,
        )
        await self.store.create_pipeline(pipeline)

        # Kick off async generation
        asyncio.create_task(self._run_pipeline(pipeline.pipeline_id))

        return pipeline

    def estimate_pieces(self, formats: list[ContentFormat]) -> int:
        """Estimate total content pieces for given formats."""
        return sum(FORMAT_MULTIPLIERS.get(f, 1) for f in formats)

    def estimate_hook_pieces(self, hooks: list[ContentHook]) -> int:
        """Estimate total pieces across all hooks using hook multipliers."""
        total = 0
        for hook in hooks:
            for fmt in hook.target_formats:
                total += HOOK_FORMAT_MULTIPLIERS.get(fmt, 1)
        return total

    async def _run_pipeline(self, pipeline_id: str):
        """Execute the content generation pipeline."""
        pipeline = await self.store.get_pipeline(pipeline_id)
        if not pipeline:
            return

        pipeline.status = "rendering"
        logger.info(
            f"Pipeline {pipeline_id}: rendering {len(pipeline.target_formats)} formats"
        )

        try:
            tasks = []
            multipliers = (
                HOOK_FORMAT_MULTIPLIERS if pipeline.hook else FORMAT_MULTIPLIERS
            )

            for fmt in pipeline.target_formats:
                adapter = FORMAT_ADAPTERS.get(fmt)
                if not adapter:
                    continue
                count = multipliers.get(fmt, 1)
                for i in range(count):
                    tasks.append(adapter(pipeline, i))

            pieces = await asyncio.gather(*tasks)

            for piece in pieces:
                await self.store.store_content(piece)

            pipeline.status = "ready"
            logger.info(f"Pipeline {pipeline_id}: {len(pieces)} pieces generated")

        except Exception as e:
            pipeline.status = "failed"
            logger.error(f"Pipeline {pipeline_id} failed: {e}")

    async def launch_campaign(
        self,
        campaign_title: str,
        source_url: str,
        hooks: list[ContentHook],
        brand_config: dict | None = None,
        caption_style: CaptionStyle = CaptionStyle.BOLD_IMPACT,
        aspect_ratio: str = "9:16",
        platforms: list[str] | None = None,
        max_posts_per_day: int = 3,
        language: str = "en",
        auto_schedule: bool = True,
        owner_key: str = "",
    ) -> LiveCampaignResponse:
        """
        Launch a full live content campaign.

        This is the 1-to-20 multiplication engine:
        1. For each hook, create a pipeline with hook-aware format adapters
        2. Generate all content pieces (9:16 vertical, animated captions)
        3. Auto-schedule across platforms via AlgorithmicScheduler
        """
        campaign_id = str(uuid.uuid4())

        # Assign hook IDs
        for i, hook in enumerate(hooks):
            if not hook.hook_id:
                hook.hook_id = f"hook-{campaign_id[:8]}-{i}"

        campaign = LiveCampaign(
            campaign_id=campaign_id,
            campaign_title=campaign_title,
            source_url=source_url,
            hooks=hooks,
            owner_key=owner_key,
        )
        await self.store.create_campaign(campaign)

        # Create a pipeline per hook
        hook_results: list[CampaignHookResult] = []
        all_content_ids: list[str] = []

        for hook in hooks:
            pipeline = await self.create_pipeline(
                title=f"{campaign_title} — {hook.title}",
                target_formats=hook.target_formats,
                source_url=source_url,
                brand_config=brand_config,
                language=language,
                auto_schedule=False,  # We schedule at campaign level
                owner_key=owner_key,
                hook=hook,
                caption_style=caption_style,
                aspect_ratio=aspect_ratio,
            )
            campaign.pipeline_ids.append(pipeline.pipeline_id)

            # Wait for async pipeline to finish
            await asyncio.sleep(0.05)
            # Ensure pipeline completes
            p = await self.store.get_pipeline(pipeline.pipeline_id)
            retries = 0
            while p and p.status != "ready" and retries < 20:
                await asyncio.sleep(0.05)
                p = await self.store.get_pipeline(pipeline.pipeline_id)
                retries += 1

            # Gather results
            content = await self.store.list_by_pipeline(pipeline.pipeline_id)
            content_ids = [c.content_id for c in content]
            all_content_ids.extend(content_ids)

            pieces_by_format: dict[str, int] = defaultdict(int)
            for c in content:
                pieces_by_format[c.format.value] += 1

            hook_results.append(CampaignHookResult(
                hook_id=hook.hook_id or "",
                hook_title=hook.title,
                hook_type=hook.hook_type,
                content_pieces=content_ids,
                pieces_by_format=dict(pieces_by_format),
                total_pieces=len(content_ids),
            ))

        # Auto-schedule across platforms
        schedule_summary: dict = {}
        if auto_schedule and all_content_ids and platforms:
            recommendations = await self.scheduler.recommend(
                content_ids=all_content_ids,
                platforms=platforms,
                max_per_day=max_posts_per_day,
            )
            schedule_summary = {
                "total_scheduled": len(recommendations),
                "platforms": list(set(r.platform for r in recommendations)),
                "date_range": (
                    f"{recommendations[0].recommended_time.strftime('%Y-%m-%d')} to "
                    f"{recommendations[-1].recommended_time.strftime('%Y-%m-%d')}"
                    if recommendations else "none"
                ),
                "estimated_total_views": sum(
                    r.estimated_views or 0 for r in recommendations
                ),
                "recommendations_preview": [
                    {
                        "content_id": r.content_id,
                        "platform": r.platform,
                        "time": r.recommended_time.isoformat(),
                        "confidence": r.confidence,
                        "estimated_views": r.estimated_views,
                    }
                    for r in recommendations[:10]  # First 10 as preview
                ],
            }

        campaign.status = "completed"
        total_pieces = sum(hr.total_pieces for hr in hook_results)

        return LiveCampaignResponse(
            campaign_id=campaign_id,
            campaign_title=campaign_title,
            source_url=source_url,
            status="completed",
            hooks_processed=len(hooks),
            total_content_pieces=total_pieces,
            hook_results=hook_results,
            schedule_generated=bool(schedule_summary),
            schedule_summary=schedule_summary,
            pipeline_ids=campaign.pipeline_ids,
        )

    async def get_content(self, content_id: str) -> GeneratedContent | None:
        return await self.store.get_content(content_id)  # type: ignore[no-any-return]

    async def list_pipeline_content(self, pipeline_id: str) -> list[GeneratedContent]:
        return await self.store.list_by_pipeline(pipeline_id)  # type: ignore[no-any-return]
