import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import cached_generate
from app.ai.orchestrator import AIOrchestrator
from app.modules.titles.models import Title
from app.modules.titles.schemas import GeneratedTitlesResponse

SYSTEM_PROMPT = (
    "You are CreatorOS's Title Engine. Generate YouTube titles under 100 "
    "characters that are clear, specific, and curiosity-driving without being "
    "misleading clickbait, spam, or keyword-stuffed. Score each title honestly "
    "0-100 for clarity, specificity, curiosity, search relevance, and audience "
    "fit. Never include false claims."
)


async def generate_titles(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    owner_user_id: uuid.UUID,
    topic: str,
    topic_id: uuid.UUID | None,
    video_id: uuid.UUID | None,
    count: int,
) -> list[Title]:
    result = await cached_generate(db, orchestrator, 
        task="generate_titles",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Topic: {topic}\nGenerate exactly {count} title candidates.",
        schema=GeneratedTitlesResponse,
        user_id=owner_user_id,
    )

    titles: list[Title] = []
    for g in result.titles:
        ctr_potential = round(
            (g.clarity_score + g.specificity_score + g.curiosity_score) / 3, 1
        )
        title = Title(
            owner_user_id=owner_user_id,
            topic_id=topic_id,
            video_id=video_id,
            text=g.text,
            ctr_potential_score=ctr_potential,
            clarity_score=g.clarity_score,
            specificity_score=g.specificity_score,
            curiosity_score=g.curiosity_score,
            search_relevance_score=g.search_relevance_score,
            audience_fit_score=g.audience_fit_score,
            generated_by="ai",
        )
        db.add(title)
        titles.append(title)

    await db.commit()
    for t in titles:
        await db.refresh(t)
    titles.sort(key=lambda t: t.ctr_potential_score or 0, reverse=True)
    return titles


async def list_titles(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Title]:
    result = await db.scalars(
        select(Title).where(Title.owner_user_id == owner_user_id).order_by(Title.created_at.desc())
    )
    return list(result)
