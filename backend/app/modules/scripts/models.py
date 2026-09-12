import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ScriptFormat(str, enum.Enum):
    SHORT = "SHORT"
    FIVE_MIN = "FIVE_MIN"
    TEN_MIN = "TEN_MIN"
    FIFTEEN_MIN = "FIFTEEN_MIN"
    LONG_FORM = "LONG_FORM"


class Script(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "scripts"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    format: Mapped[ScriptFormat] = mapped_column(Enum(ScriptFormat, name="script_format"), nullable=False)

    versions: Mapped[list["ScriptVersion"]] = relationship(
        back_populates="script", cascade="all, delete-orphan", order_by="ScriptVersion.version_number"
    )


class ScriptVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Full version history — scripts are never overwritten in place."""

    __tablename__ = "script_versions"

    script_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup: Mapped[str | None] = mapped_column(Text, nullable=True)
    promise: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_points: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list
    examples: Mapped[str | None] = mapped_column(Text, nullable=True)
    transitions: Mapped[str | None] = mapped_column(Text, nullable=True)
    pattern_interrupts: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta: Mapped[str | None] = mapped_column(Text, nullable=True)
    ending: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    generated_by: Mapped[str] = mapped_column(String(32), default="ai", nullable=False)

    script: Mapped["Script"] = relationship(back_populates="versions")
