import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.thumbnails import service
from app.modules.thumbnails.schemas import (
    AttachThumbnailImageRequest,
    GenerateThumbnailBriefRequest,
    ThumbnailBriefOut,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[ThumbnailBriefOut])
async def list_briefs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_briefs(db, user.id)


@router.post("/{brief_id}/image", response_model=ThumbnailBriefOut)
async def attach_thumbnail_image(
    brief_id: uuid.UUID,
    payload: AttachThumbnailImageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Records a chosen source image (e.g. from the Pexels picker) against
    this brief. Ownership-checked like every other brief access."""
    return await service.attach_image(db, user.id, brief_id, payload.image_url, payload.image_provider)


@router.post("/generate", response_model=ThumbnailBriefOut)
async def generate_brief(
    payload: GenerateThumbnailBriefRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    return await service.generate_thumbnail_brief(
        db, orchestrator, user.id, payload.video_title, payload.video_id, payload.topic_id, payload.brand_notes
    )
