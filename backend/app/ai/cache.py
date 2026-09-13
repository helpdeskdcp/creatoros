"""Wraps AIOrchestrator.generate_structured with a deterministic, creator-
isolated, TTL-bounded DB cache.

A cache key is (task, prompt_version, model, mode, hash(system_prompt+
user_prompt), owner_user_id). Since every service already builds its
user_prompt deterministically from its real varying inputs (topic,
audience, count, ...), no separate input-key construction is needed at
call sites — swapping `orchestrator.generate_structured(...)` for
`cached_generate(db, orchestrator, ...)` is the entire integration.

Creator isolation: owner_user_id is part of the key, so one creator's
cached result is never returned for another creator's identical prompt.
TTL: entries older than `expires_at` are never served as hits (a stale row
is simply treated as a miss and overwritten) -- see purge_expired_entries()
for physically deleting them.
Invalidation: bump `prompt_version` when a prompt's wording changes
materially enough that old cached results should stop being reused, or call
invalidate_for_user() to drop one user's cached results for a task.
"""
import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.concurrency import BoundedConcurrencyProvider
from app.ai.metrics import record_metric
from app.ai.models import AIGenerationCache
from app.ai.orchestrator import AIOrchestrator, AIOrchestratorError
from app.ai.router import AIMode, ModelTier, default_tier_for_mode, resolve_ollama_model
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.modules.audit import service as audit_service

logger = get_logger("ai.cache")

T = TypeVar("T", bound=BaseModel)


def _input_hash(system_prompt: str, user_prompt: str) -> str:
    canonical = f"{system_prompt}\x00{user_prompt}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _queue_wait_ms(orchestrator: AIOrchestrator, provider_name: str) -> int | None:
    for provider in (orchestrator.primary, orchestrator.fallback):
        if provider is not None and provider.name == provider_name and isinstance(
            provider, BoundedConcurrencyProvider
        ):
            return round(provider.last_queue_wait_seconds * 1000)
    return None


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
    mode: AIMode = AIMode.FAST,
    tier: ModelTier | None = None,
    **kwargs,
) -> T:
    """Every AI-generation call in CreatorOS goes through this one function
    (hooks/titles/scripts/thumbnails/SEO/recommendations/distribution) —
    the production audit found audit logging existed only for publishing,
    not AI generation. Wiring it here covers every caller at once instead
    of touching each service module's own audit-recording logic."""
    settings = get_settings()
    # The cache key must reflect the ACTUAL model that will serve this
    # request, not just the provider name -- otherwise a CODING-tier
    # request and a FAST_SMALL-tier request for the same provider+mode+
    # prompt text would collide and hand back the wrong model's result.
    # Mirrors the resolution AIOrchestrator.generate_structured performs.
    if orchestrator.primary.name == "ollama":
        model_name = resolve_ollama_model(tier or default_tier_for_mode(mode), settings)
    else:
        model_name = orchestrator.primary.name
    input_hash = _input_hash(system_prompt, user_prompt)
    now = datetime.now(UTC)

    cached = await db.scalar(
        select(AIGenerationCache).where(
            AIGenerationCache.task == task,
            AIGenerationCache.prompt_version == prompt_version,
            AIGenerationCache.model == model_name,
            AIGenerationCache.mode == mode.value,
            AIGenerationCache.input_hash == input_hash,
            AIGenerationCache.owner_user_id == user_id,
            AIGenerationCache.expires_at > now,
        )
    )
    if cached:
        logger.info("ai_cache_hit", task=task, input_hash=input_hash, mode=mode.value)
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
        await record_metric(
            db, task=task, mode=mode.value, provider=model_name, model=model_name,
            success=True, latency_ms=0, cache_hit=True,
        )
        return schema.model_validate_json(cached.result_json)

    start = time.perf_counter()
    try:
        result, completion = await orchestrator.generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            mode=mode,
            tier=tier,
            **kwargs,
        )
    except AIOrchestratorError as exc:
        latency_ms = round((time.perf_counter() - start) * 1000)
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
            await record_metric(
                audit_db, task=task, mode=mode.value, provider=model_name, model=model_name,
                success=False, latency_ms=latency_ms, error_code=exc.code,
            )
            await audit_db.commit()
        raise

    latency_ms = round((time.perf_counter() - start) * 1000)
    expires_at = now + timedelta(hours=settings.ai_cache_ttl_hours)
    # The uniqueness constraint is on the key columns alone (not expires_at),
    # so an EXPIRED row with this exact key can already exist (the `cached`
    # lookup above filters it out as a hit, but doesn't delete it) --
    # overwrite it in place rather than inserting a second row, which would
    # violate uq_ai_cache_key.
    stale_row = await db.scalar(
        select(AIGenerationCache).where(
            AIGenerationCache.task == task,
            AIGenerationCache.prompt_version == prompt_version,
            AIGenerationCache.model == model_name,
            AIGenerationCache.mode == mode.value,
            AIGenerationCache.input_hash == input_hash,
            AIGenerationCache.owner_user_id == user_id,
        )
    )
    if stale_row is not None:
        stale_row.result_json = result.model_dump_json()
        stale_row.expires_at = expires_at
    else:
        db.add(
            AIGenerationCache(
                task=task,
                prompt_version=prompt_version,
                model=model_name,
                mode=mode.value,
                input_hash=input_hash,
                owner_user_id=user_id,
                result_json=result.model_dump_json(),
                expires_at=expires_at,
            )
        )
    # flush (not commit): callers each manage their own transaction boundary —
    # several call this in a loop before a single commit at the end, and an
    # eager commit here would break that atomicity (see generate_next_best_videos).
    await db.flush()
    logger.info("ai_cache_miss_stored", task=task, input_hash=input_hash, mode=mode.value)
    await audit_service.record(
        db, action_type=f"ai_generate:{task}", result="success", user_id=user_id,
        provider=model_name, authorization_state="generated", commit=False,
    )
    await record_metric(
        db, task=task, mode=mode.value, provider=completion.provider, model=completion.model,
        success=True, latency_ms=latency_ms, cache_hit=False,
        queue_wait_ms=_queue_wait_ms(orchestrator, completion.provider),
        prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens,
    )
    return result


async def invalidate_for_user(db: AsyncSession, user_id: uuid.UUID | None, task: str | None = None) -> int:
    """Drop cached AI results for one creator (optionally scoped to one
    task) -- e.g. after a change that should force fresh generation before
    the TTL naturally expires. Returns the number of rows deleted."""
    stmt = delete(AIGenerationCache).where(AIGenerationCache.owner_user_id == user_id)
    if task is not None:
        stmt = stmt.where(AIGenerationCache.task == task)
    result = await db.execute(stmt.execution_options(synchronize_session=False))
    await db.commit()
    return result.rowcount or 0


async def purge_expired_entries(db: AsyncSession) -> int:
    """Physically deletes cache rows past their TTL. A stale row is already
    never served as a hit (see the `expires_at > now` filter above) -- this
    just reclaims the table space. Safe to run on a schedule.

    synchronize_session=False: this is a pure bulk DELETE, nothing in this
    call needs the ORM session's identity map kept in sync with the rows it
    removes -- and the default "evaluate" strategy tries to re-check the
    WHERE clause client-side against already-loaded objects, which can
    raise on a naive-vs-aware datetime mismatch (e.g. a same-session object
    whose DB-round-tripped column lost tzinfo, an aiosqlite/testing-only
    quirk -- Postgres timestamptz doesn't have this problem, but skipping
    the client-side re-evaluation entirely is correct and cheaper either way).
    """
    now = datetime.now(UTC)
    result = await db.execute(
        delete(AIGenerationCache)
        .where(AIGenerationCache.expires_at <= now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0
