import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.users.models import User
from app.modules.users.schemas import UpdateUserActiveRequest, UpdateUserRoleRequest, UserOut

router = APIRouter()


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.scalars(select(User).order_by(User.created_at))
    return list(result)


@router.patch("/{user_id}/role", response_model=UserOut)
async def update_role(
    user_id: uuid.UUID,
    payload: UpdateUserRoleRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError("User not found")
    user.role = payload.role
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/active", response_model=UserOut)
async def update_active(
    user_id: uuid.UUID,
    payload: UpdateUserActiveRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError("User not found")
    user.is_active = payload.is_active
    await db.commit()
    await db.refresh(user)
    return user
