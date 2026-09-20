import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.media.models import MediaPurpose


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purpose: MediaPurpose
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    local_path: str | None = None


class PexelsPhotoOut(BaseModel):
    id: int
    width: int | None
    height: int | None
    photographer: str | None
    photographer_url: str | None
    page_url: str | None
    thumbnail_url: str | None
    # The direct, permanent CDN URL -- usable as-is for image-to-video's
    # input_image_urls without any import/download step.
    download_url: str | None


class PexelsVideoOut(BaseModel):
    id: int
    duration: int | None
    width: int | None
    height: int | None
    user: str | None
    page_url: str | None
    thumbnail_url: str | None
    download_url: str | None


class PexelsImportRequest(BaseModel):
    download_url: str
    purpose: MediaPurpose
    filename_hint: str = "pexels-import"
