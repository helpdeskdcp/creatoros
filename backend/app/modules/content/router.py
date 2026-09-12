import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.content import service
from app.modules.content.models import ContentItem
from app.modules.content.schemas import (
    ContentEventOut,
    ContentItemOut,
    CreateContentItemRequest,
    UpdateContentStatusRequest,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("/items", response_model=list[ContentItemOut])
async def list_items(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_items(db, user.id)


@router.post("/items", response_model=ContentItemOut, status_code=201)
async def create_item(
    payload: CreateContentItemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.create_item(
        db,
        user.id,
        payload.title,
        payload.topic_id,
        payload.due_at,
        payload.scheduled_publish_at,
        payload.timezone,
        payload.is_short,
        payload.notes,
    )


@router.get("/calendar", response_model=list[ContentItemOut])
async def calendar(
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.list_calendar(db, user.id, start, end)


@router.patch("/items/{item_id}/status", response_model=ContentItemOut)
async def update_status(
    item_id: uuid.UUID,
    payload: UpdateContentStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await get_owned_or_404(db, ContentItem, item_id, user.id)
    return await service.update_status(db, item, user.id, payload.status, payload.comment)


@router.get("/items/{item_id}/events", response_model=list[ContentEventOut])
async def list_events(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_owned_or_404(db, ContentItem, item_id, user.id)
    return await service.list_events(db, item_id)


@router.post("/items/{item_id}/comments", response_model=ContentEventOut, status_code=201)
async def add_comment(
    item_id: uuid.UUID,
    comment: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await get_owned_or_404(db, ContentItem, item_id, user.id)
    return await service.add_comment(db, item, user.id, comment)
