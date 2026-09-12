import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crud import get_owned_or_404
from app.core.errors import ConflictError, UnauthorizedError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.channels import service
from app.modules.channels.models import Channel
from app.modules.channels.providers.base import YouTubeProviderError
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
    """Authenticated JSON variant: the caller already holds a valid session
    (Bearer token) and posts a `code` it obtained itself (e.g. a popup-window
    flow). Kept as-is for that internal use — the public browser-redirect
    flow from Google is handled by oauth_callback_get below instead, since
    that request carries no Authorization header at all."""
    channel = await service.connect_channel_via_oauth(db, user.id, payload.code)
    return channel


@router.get("/oauth/callback")
async def oauth_callback_get(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public landing page for Google's OAuth redirect (YOUTUBE_REDIRECT_URI).

    This is a plain top-level browser navigation from Google's consent
    screen — it never carries our app's Authorization header, so the signed
    `state` JWT (see service.build_oauth_state/verify_oauth_state) is what
    identifies which CreatorOS user is completing the flow and doubles as
    CSRF protection. No route here requires auth; trust comes entirely from
    validating `state`.

    Always redirects back to the configured frontend origin (never renders
    JSON to the browser) so the SPA can show a normal success/error state.
    """
    settings = get_settings()
    frontend_origin = settings.cors_origin_list[0] if settings.cors_origin_list else ""

    if error:
        return RedirectResponse(f"{frontend_origin}/channels?oauth_error={error}")
    if not code or not state:
        return RedirectResponse(f"{frontend_origin}/channels?oauth_error=missing_code_or_state")

    try:
        user_id = service.verify_oauth_state(state)
    except UnauthorizedError:
        return RedirectResponse(f"{frontend_origin}/channels?oauth_error=invalid_state")

    try:
        channel = await service.connect_channel_via_oauth(db, user_id, code)
    except (YouTubeProviderError, ConflictError):
        return RedirectResponse(f"{frontend_origin}/channels?oauth_error=connect_failed")

    return RedirectResponse(f"{frontend_origin}/channels?connected={channel.id}")


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
