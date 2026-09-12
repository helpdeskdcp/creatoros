import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tracks every background job invocation for observability + idempotency.
    Celery owns execution; this table is the source of truth for status/logs
    shown in the UI and used by the safety gate to prevent duplicate runs."""

    __tablename__ = "jobs"

    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)


class KillSwitch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Growth OS emergency stop. A single row per user (scope='global' rows
    are reserved for a future admin-level kill switch). Every autonomous
    publishing/distribution task checks this before starting new work; it
    never cancels work already in flight, and never deletes data."""

    __tablename__ = "kill_switches"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
