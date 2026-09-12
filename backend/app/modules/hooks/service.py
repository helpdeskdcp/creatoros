import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIOrchestrator
from app.modules.hooks.models import Hook
from app.modules.hooks.schemas import GeneratedHooksResponse

SYSTEM_PROMPT = (
    "You are CreatorOS's Hook Engine. Generate short, punchy video-opening hooks "
    "for YouTube creators. Cover a mix of categories: curiosity, problem, "
    "contrarian, data-driven, story, question, urgency, transformation. Score "
    "each hook honestly on a 0-100 scale for clarity, curiosity, specificity, "
    "and audience fit. Never claim a hook will guarantee views."
)


async def generate_hooks(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    owner_user_id: uuid.UUID,
    topic: str,
    topic_id: uuid.UUID | None,
    audience: str | None,
    count: int,
) -> list[Hook]:
    user_prompt = (
        f"Topic: {topic}\n"
        f"Target audience: {audience or 'general YouTube audience'}\n"
        f"Generate exactly {count} hooks."
    )
    result = await orchestrator.generate_structured(
        task="generate_hooks",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=GeneratedHooksResponse,
    )

    hooks: list[Hook] = []
    for g in result.hooks:
        hook_score = round(
            (g.clarity_score + g.curiosity_score + g.specificity_score + g.audience_fit_score) / 4, 1
        )
        hook = Hook(
            owner_user_id=owner_user_id,
            topic_id=topic_id,
            text=g.text,
            category=g.category,
            hook_score=hook_score,
            clarity_score=g.clarity_score,
            curiosity_score=g.curiosity_score,
            specificity_score=g.specificity_score,
            audience_fit_score=g.audience_fit_score,
            generated_by="ai",
        )
        db.add(hook)
        hooks.append(hook)

    await db.commit()
    for h in hooks:
        await db.refresh(h)
    hooks.sort(key=lambda h: h.hook_score or 0, reverse=True)
    return hooks


async def list_hooks(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Hook]:
    result = await db.scalars(
        select(Hook).where(Hook.owner_user_id == owner_user_id).order_by(Hook.created_at.desc())
    )
    return list(result)
