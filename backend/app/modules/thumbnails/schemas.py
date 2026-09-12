import uuid

from pydantic import BaseModel, ConfigDict, Field


class GenerateThumbnailBriefRequest(BaseModel):
    video_title: str
    video_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    brand_notes: str | None = None


class ThumbnailBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    emotion: str | None
    text_overlay: str | None
    text_overlay_length: int | None
    visual_hierarchy_notes: str | None
    contrast_notes: str | None
    curiosity_notes: str | None
    brand_consistency_notes: str | None
    prompt: str | None
    version: int


class _GeneratedThumbnailBrief(BaseModel):
    subject: str
    emotion: str
    text_overlay: str = Field(max_length=40)
    visual_hierarchy_notes: str
    contrast_notes: str
    curiosity_notes: str
    brand_consistency_notes: str
    image_prompt: str
