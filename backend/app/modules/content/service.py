import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ContentEvent, ContentItem, ContentStatus


async def create_item(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    title: str,
    topic_id: uuid.UUID | None,
    due_at: datetime | None,
    scheduled_publish_at: datetime | None,
    timezone: str,
    is_short: bool,
    notes: str | None,
) -> ContentItem:
    item = ContentItem(
        owner_user_id=owner_user_id,
        title=title,
        topic_id=topic_id,
        due_at=due_at,
        scheduled_publish_at=scheduled_publish_at,
        timezone=timezone,
        is_short=is_short,
        notes=notes,
    )
    db.add(item)
    await db.flush()
    db.add(
        ContentEvent(
            content_item_id=item.id,
            actor_user_id=owner_user_id,
            event_type="status_change",
            to_status=ContentStatus.IDEA,
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


async def list_items(db: AsyncSession, owner_user_id: uuid.UUID) -> list[ContentItem]:
    result = await db.scalars(
        select(ContentItem)
        .where(ContentItem.owner_user_id == owner_user_id)
        .order_by(ContentItem.created_at.desc())
    )
    return list(result)


async def list_calendar(
    db: AsyncSession, owner_user_id: uuid.UUID, start: datetime, end: datetime
) -> list[ContentItem]:
    result = await db.scalars(
        select(ContentItem).where(
            ContentItem.owner_user_id == owner_user_id,
            ContentItem.scheduled_publish_at.is_not(None),
            ContentItem.scheduled_publish_at >= start,
            ContentItem.scheduled_publish_at <= end,
        )
    )
    return list(result)


async def update_status(
    db: AsyncSession,
    item: ContentItem,
    actor_user_id: uuid.UUID,
    new_status: ContentStatus,
    comment: str | None,
) -> ContentItem:
    old_status = item.status
    item.status = new_status
    db.add(
        ContentEvent(
            content_item_id=item.id,
            actor_user_id=actor_user_id,
            event_type="status_change",
            from_status=old_status,
            to_status=new_status,
            comment=comment,
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


async def add_comment(
    db: AsyncSession, item: ContentItem, actor_user_id: uuid.UUID, comment: str
) -> ContentEvent:
    event = ContentEvent(
        content_item_id=item.id, actor_user_id=actor_user_id, event_type="comment", comment=comment
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def list_events(db: AsyncSession, item_id: uuid.UUID) -> list[ContentEvent]:
    result = await db.scalars(
        select(ContentEvent)
        .where(ContentEvent.content_item_id == item_id)
        .order_by(ContentEvent.created_at)
    )
    return list(result)
