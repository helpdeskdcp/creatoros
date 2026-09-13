import json
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.shorts.models import ShortCandidateStatus, VideoJobStatus


class CreateVideoJobRequest(BaseModel):
    source_media_asset_id: uuid.UUID
    idempotency_key: str


class VideoProcessingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: VideoJobStatus
    progress_pct: int
    error: str | None
    source_duration_seconds: float | None
    created_at: datetime
    updated_at: datetime


class ShortCandidateOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    rank: int
    start_seconds: float
    end_seconds: float
    score: float
    score_breakdown: dict
    transcript_excerpt: str
    status: ShortCandidateStatus
    generated_title: str | None
    generated_description: str | None
    generated_hook: str | None
    rendered_media_asset_id: uuid.UUID | None
    render_error: str | None
    rendered_at: datetime | None

    @classmethod
    def from_model(cls, candidate) -> "ShortCandidateOut":
        return cls(
            id=candidate.id, job_id=candidate.job_id, rank=candidate.rank,
            start_seconds=candidate.start_seconds, end_seconds=candidate.end_seconds,
            score=candidate.score, score_breakdown=candidate.score_breakdown_json,
            transcript_excerpt=candidate.transcript_excerpt, status=candidate.status,
            generated_title=candidate.generated_title, generated_description=candidate.generated_description,
            generated_hook=candidate.generated_hook, rendered_media_asset_id=candidate.rendered_media_asset_id,
            render_error=candidate.render_error, rendered_at=candidate.rendered_at,
        )
