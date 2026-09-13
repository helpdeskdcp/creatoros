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
import uuid
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIGenerationCache
from app.ai.orchestrator import AIOrchestratorError
from app.db.session import AsyncSessionLocal
from app.modules.audit import service as audit_service
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
    user_id: uuid.UUID | None = None,
    **kwargs,
) -> T:
    """Every AI-generation call in CreatorOS goes through this one function
    (hooks/titles/scripts/thumbnails/SEO/recommendations/distribution) —
    the production audit found audit logging existed only for publishing,
    not AI generation. Wiring it here covers every caller at once instead
    of touching each service module's own audit-recording logic."""
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
        # commit=False: cached_generate is called mid-batch by several
        # callers (e.g. generate_next_best_videos loops several of these
        # before one final commit) -- an eager commit here would break
        # that documented atomicity. Success audits share the caller's
        # transaction fate, which is correct: if the whole request rolls
        # back, "we generated this" rolling back with it is consistent.
        await audit_service.record(
            db, action_type=f"ai_generate:{task}", result="success", user_id=user_id,
            provider=model_name, authorization_state="cache_hit", commit=False,
        )
        return schema.model_validate_json(cached.result_json)

    try:
        result = await orchestrator.generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            **kwargs,
        )
    except AIOrchestratorError as exc:
        # Deliberately NOT using `db` here: get_db()'s exception handler
        # rolls back the whole session on any unhandled error, which this
        # exception will become once it propagates past this point -- a
        # failure audit record written into that same session would be
        # wiped by that rollback, defeating the point of auditing
        # failures. Use a standalone session so it survives regardless.
        async with AsyncSessionLocal() as audit_db:
            await audit_service.record(
                audit_db, action_type=f"ai_generate:{task}", result="failure", user_id=user_id,
                provider=model_name, failure_reason=str(exc),
            )
        raise

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
    await audit_service.record(
        db, action_type=f"ai_generate:{task}", result="success", user_id=user_id,
        provider=model_name, authorization_state="generated", commit=False,
    )
    return result
