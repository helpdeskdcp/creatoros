import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.notifications.models import Notification, NotificationChannel, NotificationEvent
from app.modules.notifications.providers.base import NotificationProviderError
from app.modules.notifications.providers.email_provider import SmtpEmailProvider
from app.modules.notifications.providers.in_app_provider import InAppProvider
from app.modules.notifications.providers.telegram_provider import TelegramProvider


def _provider_for(channel: NotificationChannel):
    settings = get_settings()
    if channel == NotificationChannel.EMAIL:
        return SmtpEmailProvider(settings)
    if channel == NotificationChannel.TELEGRAM:
        return TelegramProvider(settings)
    return InAppProvider()


async def notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    event: NotificationEvent,
    channel: NotificationChannel,
    title: str,
    body: str,
    recipient: str = "",
) -> Notification:
    notification = Notification(
        user_id=user_id, event=event, channel=channel, title=title, body=body
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    provider = _provider_for(channel)
    try:
        if channel == NotificationChannel.EMAIL:
            # SmtpEmailProvider.send() uses blocking smtplib; keep it off the event loop.
            await asyncio.to_thread(_run_sync_send, provider, recipient, title, body)
        else:
            await provider.send(to=recipient, title=title, body=body)
        notification.sent_at = datetime.now(UTC)
    except NotificationProviderError as exc:
        notification.delivery_error = str(exc)
    await db.commit()
    await db.refresh(notification)
    return notification


def _run_sync_send(provider, recipient: str, title: str, body: str) -> None:
    asyncio.run(provider.send(to=recipient, title=title, body=body))


async def list_notifications(db: AsyncSession, user_id: uuid.UUID) -> list[Notification]:
    result = await db.scalars(
        select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
    )
    return list(result)


async def mark_read(db: AsyncSession, notification: Notification) -> Notification:
    notification.is_read = True
    await db.commit()
    await db.refresh(notification)
    return notification
