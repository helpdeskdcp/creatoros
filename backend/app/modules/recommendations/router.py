from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.recommendations import service
from app.modules.recommendations.schemas import RecommendationOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[RecommendationOut])
async def list_recommendations(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    recs = await service.list_recommendations(db, user.id)
    return [RecommendationOut.from_model(r) for r in recs]


@router.post("/next-best-video", response_model=list[RecommendationOut])
async def next_best_video(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    recs = await service.generate_next_best_videos(db, orchestrator, user.id)
    return [RecommendationOut.from_model(r) for r in recs]
