import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.channels.models import Channel
from app.modules.users.models import User
from app.modules.videos import service
from app.modules.videos.schemas import ChannelIntelligence, VideoOut

router = APIRouter()


@router.get("/channel/{channel_id}", response_model=list[VideoOut])
async def list_videos(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.list_channel_videos(db, channel_id)


@router.get("/channel/{channel_id}/intelligence", response_model=ChannelIntelligence)
async def channel_intelligence(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.compute_channel_intelligence(db, channel)
