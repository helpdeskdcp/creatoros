import json
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.thumbnail_vision import service
from app.modules.thumbnail_vision.models import ThumbnailAnalysis
from app.modules.thumbnail_vision.schemas import ThumbnailAnalysisOut
from app.modules.users.models import User

router = APIRouter()


def _to_out(analysis: ThumbnailAnalysis) -> ThumbnailAnalysisOut:
    return ThumbnailAnalysisOut(
        id=analysis.id, video_id=analysis.video_id, image_url=analysis.image_url,
        width=analysis.width, height=analysis.height,
        meets_min_resolution=analysis.meets_min_resolution, meets_aspect_ratio=analysis.meets_aspect_ratio,
        contrast_score=analysis.contrast_score, brightness_score=analysis.brightness_score,
        colorfulness_score=analysis.colorfulness_score, subject_prominence_score=analysis.subject_prominence_score,
        recommendations=json.loads(analysis.recommendations_json), analyzed_at=analysis.analyzed_at,
    )


@router.post("/videos/{video_id}/analyze", response_model=ThumbnailAnalysisOut, status_code=201)
async def analyze_thumbnail(
    video_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    analysis = await service.analyze_video_thumbnail(db, video_id, user.id)
    return _to_out(analysis)


@router.get("/videos/{video_id}", response_model=list[ThumbnailAnalysisOut])
async def list_thumbnail_analyses(
    video_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    analyses = await service.list_analyses_for_video(db, video_id, user.id)
    return [_to_out(a) for a in analyses]
