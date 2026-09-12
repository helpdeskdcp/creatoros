from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.hooks import service
from app.modules.hooks.schemas import GenerateHooksRequest, HookOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[HookOut])
async def list_hooks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_hooks(db, user.id)


@router.post("/generate", response_model=list[HookOut])
async def generate_hooks(
    payload: GenerateHooksRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    return await service.generate_hooks(
        db, orchestrator, user.id, payload.topic, payload.topic_id, payload.audience, payload.count
    )
