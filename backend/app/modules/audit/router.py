from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.audit import service
from app.modules.audit.schemas import AuditLogOut
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[AuditLogOut])
async def list_my_audit_logs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_logs(db, user_id=user.id)
