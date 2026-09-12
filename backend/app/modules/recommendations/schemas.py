import uuid

from pydantic import BaseModel, Field


class RecommendationOut(BaseModel):
    id: uuid.UUID
    rank: int
    topic: str
    format: str
    target_audience: str | None
    content_angle: str | None
    hook: str | None
    title_candidates: list[str]
    thumbnail_concept: str | None
    reason: str
    supporting_evidence: str | None
    opportunity_score: float | None
    viral_potential_score: float | None
    discovery_score: float | None
    subscriber_potential_score: float | None
    retention_potential_score: float | None
    audience_fit_score: float | None
    confidence: str
    sample_size: int

    model_config = {"from_attributes": False}

    @classmethod
    def from_model(cls, rec) -> "RecommendationOut":
        import json

        return cls(
            id=rec.id,
            rank=rec.rank,
            topic=rec.topic,
            format=rec.format,
            target_audience=rec.target_audience,
            content_angle=rec.content_angle,
            hook=rec.hook,
            title_candidates=json.loads(rec.title_candidates_json) if rec.title_candidates_json else [],
            thumbnail_concept=rec.thumbnail_concept,
            reason=rec.reason,
            supporting_evidence=rec.supporting_evidence,
            opportunity_score=rec.opportunity_score,
            viral_potential_score=rec.viral_potential_score,
            discovery_score=rec.discovery_score,
            subscriber_potential_score=rec.subscriber_potential_score,
            retention_potential_score=rec.retention_potential_score,
            audience_fit_score=rec.audience_fit_score,
            confidence=rec.confidence,
            sample_size=rec.sample_size,
        )


class _GeneratedRecommendationDetail(BaseModel):
    target_audience: str
    content_angle: str
    hook: str
    title_candidates: list[str] = Field(min_length=3, max_length=5)
    thumbnail_concept: str
    format: str
    viral_potential_score: float = Field(ge=0, le=100)
    discovery_score: float = Field(ge=0, le=100)
    subscriber_potential_score: float = Field(ge=0, le=100)
    retention_potential_score: float = Field(ge=0, le=100)
    audience_fit_score: float = Field(ge=0, le=100)
    reasoning: str
