import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.retention import service
from app.modules.retention.schemas import RetentionMetricOut
from app.modules.users.models import User

router = APIRouter()


@router.get("/video/{video_id}", response_model=list[RetentionMetricOut])
async def list_retention(
    video_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await service.list_retention(db, video_id)


@router.post("/video/{video_id}/compute", response_model=RetentionMetricOut)
async def compute_retention(
    video_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await service.compute_retention(db, video_id)
