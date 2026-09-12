import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import cached_generate
from app.ai.orchestrator import AIOrchestrator
from app.modules.thumbnails.models import ThumbnailBrief
from app.modules.thumbnails.schemas import _GeneratedThumbnailBrief

SYSTEM_PROMPT = (
    "You are CreatorOS's Thumbnail Intelligence system. Plan (do not draw) a "
    "high-CTR YouTube thumbnail: subject, emotion, a very short text overlay "
    "(<=40 chars), notes on visual hierarchy, contrast, curiosity gap, and "
    "brand consistency, plus an image-generation prompt for a downstream "
    "image provider. Never suggest misleading or shocking-for-its-own-sake "
    "imagery."
)


async def generate_thumbnail_brief(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    owner_user_id: uuid.UUID,
    video_title: str,
    video_id: uuid.UUID | None,
    topic_id: uuid.UUID | None,
    brand_notes: str | None,
) -> ThumbnailBrief:
    user_prompt = f"Video title: {video_title}\nBrand notes: {brand_notes or 'none provided'}"
    result: _GeneratedThumbnailBrief = await cached_generate(db, orchestrator, 
        task="generate_thumbnail_brief",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=_GeneratedThumbnailBrief,
    )

    brief = ThumbnailBrief(
        owner_user_id=owner_user_id,
        video_id=video_id,
        topic_id=topic_id,
        subject=result.subject,
        emotion=result.emotion,
        text_overlay=result.text_overlay,
        text_overlay_length=len(result.text_overlay),
        visual_hierarchy_notes=result.visual_hierarchy_notes,
        contrast_notes=result.contrast_notes,
        curiosity_notes=result.curiosity_notes,
        brand_consistency_notes=result.brand_consistency_notes,
        prompt=result.image_prompt,
        version=1,
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


async def list_briefs(db: AsyncSession, owner_user_id: uuid.UUID) -> list[ThumbnailBrief]:
    result = await db.scalars(
        select(ThumbnailBrief)
        .where(ThumbnailBrief.owner_user_id == owner_user_id)
        .order_by(ThumbnailBrief.created_at.desc())
    )
    return list(result)
