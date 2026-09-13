import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import cached_generate
from app.ai.orchestrator import AIOrchestrator
from app.modules.seo.models import SeoRecord
from app.modules.seo.schemas import _GeneratedSeo

SYSTEM_PROMPT = (
    "You are CreatorOS's SEO Engine. Generate natural, non-spammy SEO metadata "
    "for a YouTube video: title suggestions, an optimized description, "
    "keywords, tags, timestamped chapters, hashtags, the likely search intent, "
    "and topic clusters. Never keyword-stuff or fabricate claims."
)


async def generate_seo(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    owner_user_id: uuid.UUID,
    title: str,
    description: str,
    video_id: uuid.UUID | None,
) -> SeoRecord:
    result: _GeneratedSeo = await cached_generate(db, orchestrator, 
        task="generate_seo",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Video title: {title}\nVideo description/summary: {description}",
        schema=_GeneratedSeo,
        user_id=owner_user_id,
    )

    record = SeoRecord(
        owner_user_id=owner_user_id,
        video_id=video_id,
        title_suggestions=json.dumps(result.title_suggestions),
        description=result.description,
        keywords=json.dumps(result.keywords),
        tags=json.dumps(result.tags),
        chapters=json.dumps([c.model_dump() for c in result.chapters]),
        hashtags=json.dumps(result.hashtags),
        search_intent=result.search_intent,
        topic_clusters=json.dumps(result.topic_clusters),
        generated_by="ai",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def list_seo_records(db: AsyncSession, owner_user_id: uuid.UUID) -> list[SeoRecord]:
    result = await db.scalars(
        select(SeoRecord)
        .where(SeoRecord.owner_user_id == owner_user_id)
        .order_by(SeoRecord.created_at.desc())
    )
    return list(result)
