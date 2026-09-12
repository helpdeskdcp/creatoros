import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.publishing.models import PublishingMode, PublishingState


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


class PublishingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    mode: PublishingMode
    state: PublishingState
    youtube_video_id: str | None
    failure_reason: str | None
    requires_approval: bool
    approved_at: datetime | None


class SafetyGateResultOut(BaseModel):
    passed: bool
    checks: list[dict]
    block_reason: str | None
