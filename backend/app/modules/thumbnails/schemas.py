import uuid

from pydantic import BaseModel, ConfigDict, Field


class GenerateThumbnailBriefRequest(BaseModel):
    video_title: str
    video_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    brand_notes: str | None = None


class AttachThumbnailImageRequest(BaseModel):
    # A direct, permanent image URL (e.g. a Pexels photo's download_url) --
    # not re-downloaded/stored as a separate MediaAsset, same treatment as
    # image-to-video's source-image URLs, since nothing downstream
    # currently consumes image_path as a local file path (see
    # ThumbnailBrief's docstring: "the resulting asset URL/path").
    image_url: str
    image_provider: str = "pexels"


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
    image_path: str | None
    image_provider: str | None
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
