import json
import uuid

from pydantic import BaseModel, ConfigDict, Field


class GenerateSeoRequest(BaseModel):
    title: str
    description: str
    video_id: uuid.UUID | None = None


class ChapterOut(BaseModel):
    time: str
    title: str


class SeoRecordOut(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID | None
    title_suggestions: list[str]
    description: str | None
    keywords: list[str]
    tags: list[str]
    chapters: list[ChapterOut]
    hashtags: list[str]
    search_intent: str | None
    topic_clusters: list[str]
    generated_by: str

    model_config = ConfigDict(from_attributes=False)

    @classmethod
    def from_model(cls, record) -> "SeoRecordOut":
        def _list(value: str | None) -> list:
            return json.loads(value) if value else []

        return cls(
            id=record.id,
            video_id=record.video_id,
            title_suggestions=_list(record.title_suggestions),
            description=record.description,
            keywords=_list(record.keywords),
            tags=_list(record.tags),
            chapters=[ChapterOut(**c) for c in _list(record.chapters)],
            hashtags=_list(record.hashtags),
            search_intent=record.search_intent,
            topic_clusters=_list(record.topic_clusters),
            generated_by=record.generated_by,
        )


class _GeneratedSeo(BaseModel):
    title_suggestions: list[str] = Field(max_length=5)
    description: str
    keywords: list[str]
    tags: list[str]
    chapters: list[ChapterOut]
    hashtags: list[str]
    search_intent: str
    topic_clusters: list[str]
