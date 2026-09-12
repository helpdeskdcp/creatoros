"""Small generic helpers shared by every module's simple CRUD endpoints.

Kept intentionally minimal: anything with real domain logic (scoring,
INSUFFICIENT_DATA checks, AI generation) belongs in that module's own
service.py, not here.
"""
import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError

ModelT = TypeVar("ModelT")


async def list_owned(
    db: AsyncSession,
    model: type[ModelT],
    owner_user_id: uuid.UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[ModelT]:
    stmt = (
        select(model)
        .where(model.owner_user_id == owner_user_id)  # type: ignore[attr-defined]
        .order_by(model.created_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
        .offset(offset)
    )
    return list(await db.scalars(stmt))


async def get_owned_or_404(
    db: AsyncSession, model: type[ModelT], obj_id: uuid.UUID, owner_user_id: uuid.UUID
) -> ModelT:
    obj = await db.get(model, obj_id)
    if not obj or getattr(obj, "owner_user_id", None) != owner_user_id:
        raise NotFoundError(f"{model.__name__} not found")
    return obj


async def delete_owned(
    db: AsyncSession, model: type[ModelT], obj_id: uuid.UUID, owner_user_id: uuid.UUID
) -> None:
    obj = await get_owned_or_404(db, model, obj_id, owner_user_id)
    await db.delete(obj)
    await db.commit()
