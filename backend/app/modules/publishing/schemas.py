import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.modules.publishing.models import PublishingMode, PublishingState


def _require_tz_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone offset (e.g. ...+00:00 or ...Z)")
    return value


class UpdatePublishingRuleRequest(BaseModel):
    mode: PublishingMode | None = None
    is_enabled: bool | None = None
    max_videos_per_day: int | None = None
    minimum_content_score: float | None = None
    minimum_subscriber_score: float | None = None
    require_thumbnail: bool | None = None
    require_metadata_validation: bool | None = None


class PublishingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    mode: PublishingMode
    is_enabled: bool
    max_videos_per_day: int
    minimum_content_score: float
    minimum_subscriber_score: float
    require_thumbnail: bool
    require_metadata_validation: bool
    expires_at: datetime | None


class CreatePublishingRunRequest(BaseModel):
    channel_id: uuid.UUID
    content_item_id: uuid.UUID | None = None
    mode: PublishingMode
    idempotency_key: str
    title: str
    description: str
    tags: list[str] = []
    category_id: str = "22"
    privacy_status: str = "private"
    thumbnail_path: str | None = None
    content_score: float = 0.0
    subscriber_score: float = 0.0
    media_asset_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None

    _validate_scheduled_at = field_validator("scheduled_at")(_require_tz_aware)


class RescheduleRunRequest(BaseModel):
    scheduled_at: datetime | None  # None = publish immediately on next approval/poll

    _validate_scheduled_at = field_validator("scheduled_at")(_require_tz_aware)


class PublishingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    mode: PublishingMode
    state: PublishingState
    youtube_video_id: str | None
    published_url: str | None
    published_at: datetime | None
    failure_reason: str | None
    requires_approval: bool
    approved_at: datetime | None
    scheduled_at: datetime | None
    cancelled_at: datetime | None
    retry_count: int


class ExecuteRunResultOut(BaseModel):
    run: PublishingRunOut
    result: str  # succeeded | processing | failed | configuration_required | blocked


class SafetyGateResultOut(BaseModel):
    passed: bool
    checks: list[dict]
    block_reason: str | None
