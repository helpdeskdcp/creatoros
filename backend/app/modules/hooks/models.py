import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class HookCategory(str, enum.Enum):
    CURIOSITY = "curiosity"
    PROBLEM = "problem"
    CONTRARIAN = "contrarian"
    DATA_DRIVEN = "data-driven"
    STORY = "story"
    QUESTION = "question"
    URGENCY = "urgency"
    TRANSFORMATION = "transformation"


class Hook(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "hooks"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[HookCategory] = mapped_column(
        Enum(HookCategory, name="hook_category"), nullable=False
    )

    hook_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    clarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    curiosity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    specificity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    audience_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_by: Mapped[str] = mapped_column(String(32), default="ai", nullable=False)
