"""AI generation cache: identical (task, prompt_version, model, mode,
creator, prompts) never calls the provider twice. Directly reduces AI
token/API cost per the Growth OS token-optimization policy — see docs/ai.md.

Cache entries are creator-isolated (`owner_user_id`) and expire (`expires_at`)
-- a cached result is only ever reused for the same user, and only until it
goes stale, never served forever."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class AIGenerationCache(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_generation_cache"
    __table_args__ = (
        UniqueConstraint(
            "task", "prompt_version", "model", "mode", "input_hash", "owner_user_id",
            name="uq_ai_cache_key",
        ),
    )

    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # "fast" | "deep" -- part of the cache key so a DEEP (think=true) result
    # is never handed back for a FAST request or vice versa.
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default="fast")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nullable: some callers (e.g. a system-triggered background job with no
    # single owning user) legitimately have no creator to isolate by; NULL
    # participates in the uniqueness constraint as its own bucket, never
    # matching a real user's row (SQL NULL <> NULL).
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AIRequestMetric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per AI generation attempt (cache hit or miss). Deliberately
    excludes prompt/response content and user identity beyond a coarse
    task label -- this is for latency/failure-rate observability, not an
    audit trail (see app.modules.audit for that)."""

    __tablename__ = "ai_request_metrics"

    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    queue_wait_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
