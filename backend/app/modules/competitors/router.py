import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404, list_owned
from app.core.data_quality import Metric
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.competitors import service
from app.modules.competitors.models import Competitor, CompetitorVideo
from app.modules.competitors.schemas import (
    AddCompetitorRequest,
    CompetitorOut,
    CompetitorVideoOut,
    ContentGap,
    FormatBreakdown,
    GapToTopicResult,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[CompetitorOut])
async def list_competitors(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await list_owned(db, Competitor, user.id)


@router.post("", response_model=CompetitorOut, status_code=201)
async def add_competitor(
    payload: AddCompetitorRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await service.add_competitor(db, user.id, payload.youtube_channel_id, payload.notes)


@router.post("/{competitor_id}/sync", response_model=CompetitorOut)
async def sync_competitor(
    competitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    await get_owned_or_404(db, Competitor, competitor_id, user.id)
    return await service.sync_competitor(db, competitor_id)


@router.get("/{competitor_id}/videos", response_model=list[CompetitorVideoOut])
async def list_competitor_videos(
    competitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_owned_or_404(db, Competitor, competitor_id, user.id)
    result = await db.scalars(
        select(CompetitorVideo)
        .where(CompetitorVideo.competitor_id == competitor_id)
        .order_by(CompetitorVideo.published_at.desc())
    )
    return list(result)


@router.get("/opportunities/content-gaps", response_model=list[ContentGap])
async def content_gaps(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.detect_content_gaps(db, user.id)


@router.post("/opportunities/content-gaps/create-topics", response_model=list[GapToTopicResult])
async def gaps_to_topics(
    top_n: int = 5, db: AsyncSession = Depends(get_db), user: User = Depends(require_editor)
):
    """Connects gap detection to the existing topic/opportunity/
    recommendation pipeline instead of leaving it an isolated report."""
    return await service.create_topics_from_content_gaps(db, user.id, top_n)


@router.get("/{competitor_id}/traction", response_model=Metric[float])
async def competitor_traction(
    competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, Competitor, competitor_id, user.id)
    return await service.compute_competitor_traction(db, competitor_id)


@router.get("/{competitor_id}/cadence", response_model=Metric[float])
async def competitor_cadence(
    competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, Competitor, competitor_id, user.id)
    return await service.analyze_competitor_cadence(db, competitor_id)


@router.get("/{competitor_id}/formats", response_model=FormatBreakdown)
async def competitor_formats(
    competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, Competitor, competitor_id, user.id)
    return await service.analyze_competitor_formats(db, competitor_id)
