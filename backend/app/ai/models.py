"""AI generation cache: identical (task, prompt_version, model, prompts)
never calls the provider twice. Directly reduces AI token/API cost per the
Growth OS token-optimization policy — see docs/ai.md."""
from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIGenerationCache(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_generation_cache"
    __table_args__ = (
        UniqueConstraint(
            "task", "prompt_version", "model", "input_hash", name="uq_ai_cache_key"
        ),
    )

    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
