import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.distribution.models import AssetStatus, CampaignStatus, Platform


class CreateCampaignRequest(BaseModel):
    name: str
    source_video_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: CampaignStatus
    source_video_id: uuid.UUID | None
    starts_at: datetime | None
    ends_at: datetime | None


class GenerateAssetsRequest(BaseModel):
    source_segment: str | None = None
    source_transcript_excerpt: str
    platforms: list[Platform] = Field(default_factory=lambda: [Platform.INSTAGRAM, Platform.X])


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: Platform
    format: str
    hook: str | None
    caption: str | None
    cta: str | None
    title: str | None
    status: AssetStatus
    scheduled_at: datetime | None
    published_at: datetime | None
    publication_status: str | None


class _GeneratedAsset(BaseModel):
    platform: Platform
    format: str
    hook: str
    caption: str
    cta: str
    title: str


class GeneratedAssetsResponse(BaseModel):
    assets: list[_GeneratedAsset]
