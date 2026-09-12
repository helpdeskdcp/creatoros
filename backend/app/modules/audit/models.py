import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import GUID


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """Append-only. Never write OAuth tokens/API keys/passwords into this
    table — see app.modules.audit.service.record() which enforces this."""

    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorization_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rule_set_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)  # success | failure | blocked
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
