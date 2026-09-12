from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.titles import service
from app.modules.titles.schemas import GenerateTitlesRequest, TitleOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[TitleOut])
async def list_titles(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_titles(db, user.id)


@router.post("/generate", response_model=list[TitleOut])
async def generate_titles(
    payload: GenerateTitlesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    return await service.generate_titles(
        db, orchestrator, user.id, payload.topic, payload.topic_id, payload.video_id, payload.count
    )
