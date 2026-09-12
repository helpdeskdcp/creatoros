"""Wraps AIOrchestrator.generate_structured with a deterministic DB cache.

A cache key is (task, prompt_version, model, hash(system_prompt+user_prompt)).
Since every service already builds its user_prompt deterministically from
its real varying inputs (topic, audience, count, ...), no separate
input-key construction is needed at call sites — swapping
`orchestrator.generate_structured(...)` for
`cached_generate(db, orchestrator, ...)` is the entire integration.

Invalidation: bump `prompt_version` when a prompt's wording changes
materially enough that old cached results should stop being reused.
"""
import hashlib
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIGenerationCache
from app.ai.orchestrator import AIOrchestrator
from app.core.logging import get_logger

logger = get_logger("ai.cache")

T = TypeVar("T", bound=BaseModel)


def _input_hash(system_prompt: str, user_prompt: str) -> str:
    canonical = f"{system_prompt}\x00{user_prompt}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def cached_generate(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    *,
    task: str,
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    prompt_version: str = "v1",
    **kwargs,
) -> T:
    model_name = getattr(orchestrator.primary, "name", "unknown")
    input_hash = _input_hash(system_prompt, user_prompt)

    cached = await db.scalar(
        select(AIGenerationCache).where(
            AIGenerationCache.task == task,
            AIGenerationCache.prompt_version == prompt_version,
            AIGenerationCache.model == model_name,
            AIGenerationCache.input_hash == input_hash,
        )
    )
    if cached:
        logger.info("ai_cache_hit", task=task, input_hash=input_hash)
        return schema.model_validate_json(cached.result_json)

    result = await orchestrator.generate_structured(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=schema,
        **kwargs,
    )

    db.add(
        AIGenerationCache(
            task=task,
            prompt_version=prompt_version,
            model=model_name,
            input_hash=input_hash,
            result_json=result.model_dump_json(),
        )
    )
    # flush (not commit): callers each manage their own transaction boundary —
    # several call this in a loop before a single commit at the end, and an
    # eager commit here would break that atomicity (see generate_next_best_videos).
    await db.flush()
    logger.info("ai_cache_miss_stored", task=task, input_hash=input_hash)
    return result
