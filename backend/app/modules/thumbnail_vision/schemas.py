import uuid
from datetime import datetime

from pydantic import BaseModel


class ThumbnailAnalysisOut(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    image_url: str
    width: int
    height: int
    meets_min_resolution: bool
    meets_aspect_ratio: bool
    contrast_score: float
    brightness_score: float
    colorfulness_score: float
    subject_prominence_score: float
    recommendations: list[str]
    analyzed_at: datetime

    model_config = {"from_attributes": True}
