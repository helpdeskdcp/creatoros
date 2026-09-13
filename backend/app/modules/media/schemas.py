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
