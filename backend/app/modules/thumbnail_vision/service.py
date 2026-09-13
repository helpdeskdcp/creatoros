"""Thumbnail Vision Analysis service: fetches the video's real, live
thumbnail image and runs deterministic pixel analysis on it -- never an
AI-generated guess about what the thumbnail looks like."""
import json
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.thumbnail_vision.analysis import analyze_thumbnail, generate_recommendations
from app.modules.thumbnail_vision.models import ThumbnailAnalysis
from app.modules.video_updates.service import get_owned_video

_FETCH_TIMEOUT_S = 15.0
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def analyze_video_thumbnail(
    db: AsyncSession, video_id: uuid.UUID, owner_user_id: uuid.UUID
) -> ThumbnailAnalysis:
    video = await get_owned_video(db, video_id, owner_user_id)
    if not video.thumbnail_url:
        raise ValidationError("This video has no thumbnail_url synced yet -- sync the channel first")

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S) as client:
            resp = await client.get(video.thumbnail_url)
    except httpx.TransportError as exc:
        raise ValidationError(f"Could not fetch the thumbnail image: {exc}") from exc
    if resp.status_code != 200:
        raise ValidationError(f"Could not fetch the thumbnail image: HTTP {resp.status_code}")
    if len(resp.content) > _MAX_IMAGE_BYTES:
        raise ValidationError("Thumbnail image is unexpectedly large -- refusing to process")

    metrics = analyze_thumbnail(resp.content)
    recommendations = generate_recommendations(metrics)

    analysis = ThumbnailAnalysis(
        video_id=video.id,
        owner_user_id=owner_user_id,
        image_url=video.thumbnail_url,
        width=metrics.width,
        height=metrics.height,
        meets_min_resolution=metrics.meets_min_resolution,
        meets_aspect_ratio=metrics.meets_aspect_ratio,
        contrast_score=metrics.contrast_score,
        brightness_score=metrics.brightness_score,
        colorfulness_score=metrics.colorfulness_score,
        subject_prominence_score=metrics.subject_prominence_score,
        recommendations_json=json.dumps(recommendations),
        analyzed_at=datetime.now(UTC),
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    return analysis


async def list_analyses_for_video(
    db: AsyncSession, video_id: uuid.UUID, owner_user_id: uuid.UUID
) -> list[ThumbnailAnalysis]:
    await get_owned_video(db, video_id, owner_user_id)  # 404s if not owned
    result = await db.scalars(
        select(ThumbnailAnalysis)
        .where(ThumbnailAnalysis.video_id == video_id, ThumbnailAnalysis.owner_user_id == owner_user_id)
        .order_by(ThumbnailAnalysis.analyzed_at.desc())
    )
    return list(result)
