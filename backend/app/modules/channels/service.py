"""Channel connect + sync business logic. All YouTube access goes through
the YouTubeProvider interface (app.modules.channels.providers) — nothing
here imports httpx/Google APIs directly."""
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.core.errors import ConflictError, NotFoundError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import create_jwt, decode_jwt
from app.core.timeutils import ensure_aware
from app.modules.audit import service as audit_service
from app.modules.billing.entitlement import enforce_limit
from app.modules.channels.models import Channel, SyncStatus
from app.modules.channels.providers import get_youtube_provider
from app.modules.channels.providers.base import YouTubeProviderError
from app.modules.notifications.models import NotificationChannel, NotificationEvent
from app.modules.notifications.service import notify
from app.modules.videos.models import Video, VideoFormat, VideoMetricSnapshot

logger = get_logger("channels.service")


def build_oauth_state(user_id: uuid.UUID) -> str:
    token, _ = create_jwt(subject=str(user_id), token_type="access", extra_claims={"purpose": "yt_oauth"})
    return token


def verify_oauth_state(state: str) -> uuid.UUID:
    """Validates the signed `state` JWT Google echoes back on redirect.

    This request comes straight from the user's browser (a top-level
    navigation from Google's consent screen), never carrying our normal
    Authorization header — `state` is the only thing tying this request back
    to the CreatorOS user who started the flow. Since it's HMAC-signed with
    JWT_SECRET, Google can only ever echo back exactly what we handed it,
    which is what makes this CSRF-safe: an attacker cannot forge a state
    value that decodes to a different, arbitrary user_id.
    """
    try:
        payload = decode_jwt(state)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("OAuth state is invalid or has expired") from exc
    if payload.get("purpose") != "yt_oauth":
        raise UnauthorizedError("OAuth state was not issued for this flow")
    return uuid.UUID(payload["sub"])


async def get_oauth_authorize_url(user_id: uuid.UUID) -> tuple[str, str]:
    provider = get_youtube_provider()
    state = build_oauth_state(user_id)
    url = await provider.get_oauth_authorize_url(state)
    return url, state


async def connect_channel_via_oauth(db: AsyncSession, user_id: uuid.UUID, code: str) -> Channel:
    provider = get_youtube_provider()
    try:
        tokens = await provider.exchange_oauth_code(code)
        channel_data = await provider.get_channel(access_token=tokens.access_token)
    except YouTubeProviderError as exc:
        await audit_service.record(
            db, action_type="oauth_connect", result="failure", user_id=user_id,
            provider="youtube", failure_reason=str(exc),
        )
        raise

    existing = await db.scalar(
        select(Channel).where(Channel.youtube_channel_id == channel_data.youtube_channel_id)
    )
    if existing:
        # Multi-user isolation: completing OAuth for a channel someone else
        # already connected must never silently transfer ownership or
        # overwrite their tokens with this user's.
        if existing.owner_user_id != user_id:
            await audit_service.record(
                db, action_type="oauth_connect", result="blocked", user_id=user_id,
                channel_id=existing.id, provider="youtube",
                failure_reason="Channel already connected to a different CreatorOS account",
            )
            raise ConflictError(
                "This YouTube channel is already connected to a different CreatorOS account"
            )
        channel = existing
    else:
        current_count = await db.scalar(
            select(func.count()).select_from(Channel).where(Channel.owner_user_id == user_id)
        )
        await enforce_limit(db, user_id=user_id, feature="max_channels", current_count=current_count)
        channel = Channel(owner_user_id=user_id, youtube_channel_id=channel_data.youtube_channel_id)
        db.add(channel)

    channel.title = channel_data.title
    channel.description = channel_data.description
    channel.thumbnail_url = channel_data.thumbnail_url
    channel.country = channel_data.country
    channel.subscriber_count = channel_data.subscriber_count
    channel.view_count = channel_data.view_count
    channel.video_count = channel_data.video_count
    channel.oauth_access_token_encrypted = encrypt(tokens.access_token)
    if tokens.refresh_token:
        channel.oauth_refresh_token_encrypted = encrypt(tokens.refresh_token)
    channel.oauth_token_expires_at = tokens.expires_at

    await db.commit()
    await db.refresh(channel)

    await audit_service.record(
        db, action_type="oauth_connect", result="success", user_id=user_id,
        channel_id=channel.id, provider="youtube",
    )
    return channel


async def connect_channel_public(
    db: AsyncSession, user_id: uuid.UUID, youtube_channel_id: str
) -> Channel:
    """Read-only connect using only the public channel id — no OAuth, so no
    authorized analytics or publishing until the creator completes OAuth."""
    existing = await db.scalar(
        select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
    )
    if existing:
        raise ConflictError("This channel is already connected")

    current_count = await db.scalar(
        select(func.count()).select_from(Channel).where(Channel.owner_user_id == user_id)
    )
    await enforce_limit(db, user_id=user_id, feature="max_channels", current_count=current_count)

    provider = get_youtube_provider()
    channel_data = await provider.get_channel(channel_id=youtube_channel_id)

    channel = Channel(
        owner_user_id=user_id,
        youtube_channel_id=channel_data.youtube_channel_id,
        title=channel_data.title,
        description=channel_data.description,
        thumbnail_url=channel_data.thumbnail_url,
        country=channel_data.country,
        subscriber_count=channel_data.subscriber_count,
        view_count=channel_data.view_count,
        video_count=channel_data.video_count,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


async def _get_valid_access_token(db: AsyncSession, channel: Channel) -> str | None:
    """Returns a usable access token, refreshing it first if needed. Returns
    None (never a stale/guessed token) if the channel has no OAuth grant."""
    if not channel.oauth_access_token_encrypted:
        return None

    if channel.oauth_token_expires_at and ensure_aware(
        channel.oauth_token_expires_at
    ) > datetime.now(UTC) + timedelta(minutes=2):
        return decrypt(channel.oauth_access_token_encrypted)

    if not channel.oauth_refresh_token_encrypted:
        return decrypt(channel.oauth_access_token_encrypted)

    provider = get_youtube_provider()
    refresh_token = decrypt(channel.oauth_refresh_token_encrypted)
    tokens = await provider.refresh_oauth_token(refresh_token)
    channel.oauth_access_token_encrypted = encrypt(tokens.access_token)
    channel.oauth_token_expires_at = tokens.expires_at
    await db.commit()
    return tokens.access_token


async def _sync_channel_analytics(
    db: AsyncSession,
    provider,
    channel: Channel,
    access_token: str,
    now: datetime,
    snapshot_by_youtube_id: dict[str, VideoMetricSnapshot],
) -> None:
    """Populates the subscriber-growth data pipeline: without this, every
    subscriber-conversion metric in the app was permanently INSUFFICIENT_DATA
    because nothing ever called the YouTube Analytics API. Only reachable
    when this channel has completed OAuth (access_token is truthy) -- the
    yt-analytics.readonly scope is not available to public/unauthenticated
    channels, and CreatorOS never guesses this data.

    A channel that granted OAuth but declined the analytics scope
    specifically gets a 403 here (see YouTubeDataAPIProvider.
    get_channel_analytics) -- caught and skipped, not fatal to the sync,
    since the video/channel data fetched above is still real and worth
    keeping.
    """
    try:
        rows = await provider.get_channel_analytics(
            channel_id=channel.youtube_channel_id,
            access_token=access_token,
            start_date=now - timedelta(days=30),
            end_date=now,
        )
    except YouTubeProviderError as exc:
        logger.warning(
            "channel_analytics_sync_skipped", channel_id=str(channel.id), error=str(exc)
        )
        return

    by_video: dict[str, list] = {}
    for row in rows:
        by_video.setdefault(row.video_youtube_id, []).append(row)

    for youtube_video_id, video_rows in by_video.items():
        snapshot = snapshot_by_youtube_id.get(youtube_video_id)
        if not snapshot:
            continue  # video wasn't in this sync's page window -- skip rather than guess

        views = [r.views for r in video_rows if r.views is not None]
        durations = [r.average_view_duration_seconds for r in video_rows if r.average_view_duration_seconds is not None]
        percentages = [r.average_view_percentage for r in video_rows if r.average_view_percentage is not None]
        ctrs = [r.estimated_ctr for r in video_rows if r.estimated_ctr is not None]
        subs = [r.subscribers_gained for r in video_rows if r.subscribers_gained is not None]

        snapshot.window_view_count = sum(views) if views else None
        snapshot.average_view_duration_seconds = sum(durations) / len(durations) if durations else None
        snapshot.average_view_percentage = sum(percentages) / len(percentages) if percentages else None
        snapshot.estimated_ctr = sum(ctrs) / len(ctrs) if ctrs else None
        snapshot.subscribers_gained = sum(subs) if subs else None


async def sync_channel(db: AsyncSession, channel_id: uuid.UUID) -> Channel:
    """Full incremental sync: refresh channel stats, upsert every video and
    record a metrics snapshot. Idempotent — safe to run repeatedly."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise NotFoundError("Channel not found")

    was_already_failed = channel.sync_status == SyncStatus.FAILED
    channel.sync_status = SyncStatus.SYNCING
    await db.commit()

    provider = get_youtube_provider()
    try:
        access_token = await _get_valid_access_token(db, channel)
        channel_data = await provider.get_channel(
            channel_id=channel.youtube_channel_id, access_token=access_token
        )
        channel.subscriber_count = channel_data.subscriber_count
        channel.view_count = channel_data.view_count
        channel.video_count = channel_data.video_count

        page_token: str | None = None
        now = datetime.now(UTC)
        seen_pages = 0
        snapshot_by_youtube_id: dict[str, VideoMetricSnapshot] = {}
        while True:
            page = await provider.list_channel_videos(channel.youtube_channel_id, page_token)
            for vdata in page.videos:
                video = await db.scalar(
                    select(Video).where(Video.youtube_video_id == vdata.youtube_video_id)
                )
                if not video:
                    video = Video(channel_id=channel.id, youtube_video_id=vdata.youtube_video_id)
                    db.add(video)

                video.title = vdata.title
                video.description = vdata.description
                video.thumbnail_url = vdata.thumbnail_url
                video.published_at = vdata.published_at
                video.duration_seconds = vdata.duration_seconds
                video.category_id = vdata.category_id
                video.format = VideoFormat.SHORT if vdata.is_short else VideoFormat.LONG_FORM
                video.tags = ",".join(vdata.tags) if vdata.tags else None
                video.view_count = vdata.view_count
                video.like_count = vdata.like_count
                video.comment_count = vdata.comment_count
                await db.flush()

                snapshot = VideoMetricSnapshot(
                    video_id=video.id,
                    captured_at=now,
                    view_count=vdata.view_count,
                    like_count=vdata.like_count,
                    comment_count=vdata.comment_count,
                )
                db.add(snapshot)
                snapshot_by_youtube_id[vdata.youtube_video_id] = snapshot

            seen_pages += 1
            page_token = page.next_page_token
            if not page_token or seen_pages >= 20:  # hard cap: never loop forever on a bad cursor
                break

        if access_token:
            await _sync_channel_analytics(db, provider, channel, access_token, now, snapshot_by_youtube_id)

        channel.sync_status = SyncStatus.SUCCEEDED
        channel.last_synced_at = now
        channel.last_sync_error = None
        await db.commit()
        await db.refresh(channel)
        return channel
    except YouTubeProviderError as exc:
        channel.sync_status = SyncStatus.FAILED
        channel.last_sync_error = str(exc)
        await db.commit()
        logger.error("channel_sync_failed", channel_id=str(channel_id), error=str(exc))
        # Only on the transition INTO failure, not on every retry of an
        # already-failed channel -- avoids paging the creator repeatedly
        # for the same standing problem (mandate: avoid notification spam).
        if not was_already_failed:
            await notify(
                db, channel.owner_user_id, NotificationEvent.SYNC_FAILURE, NotificationChannel.IN_APP,
                f"Sync failed for {channel.title}",
                f"CreatorOS could not sync {channel.title} from YouTube: {exc}",
            )
        raise
