import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import NotificationOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[NotificationOut])
async def list_notifications(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_notifications(db, user.id)


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise NotFoundError("Notification not found")
    return await service.mark_read(db, notification)
