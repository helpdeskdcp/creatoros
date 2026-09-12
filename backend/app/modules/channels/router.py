import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.channels import service
from app.modules.channels.models import Channel
from app.modules.channels.schemas import (
    ChannelOut,
    ConnectChannelRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[ChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.scalars(
        select(Channel).where(Channel.owner_user_id == user.id).order_by(Channel.created_at.desc())
    )
    return list(result)


@router.get("/oauth/authorize", response_model=OAuthAuthorizeResponse)
async def oauth_authorize(user: User = Depends(require_editor)):
    url, state = await service.get_oauth_authorize_url(user.id)
    return OAuthAuthorizeResponse(authorize_url=url, state=state)


@router.post("/oauth/callback", response_model=ChannelOut)
async def oauth_callback(
    payload: OAuthCallbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    channel = await service.connect_channel_via_oauth(db, user.id, payload.code)
    return channel


@router.post("", response_model=ChannelOut, status_code=201)
async def connect_channel(
    payload: ConnectChannelRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    channel = await service.connect_channel_public(db, user.id, payload.youtube_channel_id)
    return channel


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_owned_or_404(db, Channel, channel_id, user.id)


@router.post("/{channel_id}/sync", response_model=ChannelOut)
async def trigger_sync(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Synchronous for now if Celery isn't reachable; the Celery task
    youtube_sync (app.jobs.tasks) wraps this same service call for the
    scheduled/production path."""
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.sync_channel(db, channel.id)
