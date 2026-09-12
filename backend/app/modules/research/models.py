import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class SourceCredibility(str, enum.Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NEEDS_REVIEW = "needs_review"


class ResearchProject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "research_projects"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "research_sources"

    research_project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    credibility: Mapped[SourceCredibility] = mapped_column(
        Enum(SourceCredibility, name="source_credibility"),
        default=SourceCredibility.NEEDS_REVIEW,
        nullable=False,
    )
    added_by_ai: Mapped[bool] = mapped_column(default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
