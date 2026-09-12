from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.seo import service
from app.modules.seo.schemas import GenerateSeoRequest, SeoRecordOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[SeoRecordOut])
async def list_seo(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    records = await service.list_seo_records(db, user.id)
    return [SeoRecordOut.from_model(r) for r in records]


@router.post("/generate", response_model=SeoRecordOut)
async def generate_seo(
    payload: GenerateSeoRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    record = await service.generate_seo(
        db, orchestrator, user.id, payload.title, payload.description, payload.video_id
    )
    return SeoRecordOut.from_model(record)
