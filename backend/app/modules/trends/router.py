from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.trends import service
from app.modules.trends.schemas import TrendOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[TrendOut])
async def list_trends(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_trends(db, user.id)


@router.post("/refresh", response_model=list[TrendOut])
async def refresh_trends(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.refresh_trends(db, user.id)
