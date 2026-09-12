import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.distribution import service
from app.modules.distribution.models import DistributionCampaign
from app.modules.distribution.schemas import (
    AssetOut,
    CampaignOut,
    CreateCampaignRequest,
    GenerateAssetsRequest,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_campaigns(db, user.id)


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    payload: CreateCampaignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await service.create_campaign(
        db, user.id, payload.name, payload.source_video_id, payload.starts_at, payload.ends_at
    )


@router.get("/campaigns/{campaign_id}/assets", response_model=list[AssetOut])
async def list_assets(
    campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, DistributionCampaign, campaign_id, user.id)
    return await service.list_assets(db, campaign_id)


@router.post("/campaigns/{campaign_id}/assets/generate", response_model=list[AssetOut])
async def generate_assets(
    campaign_id: uuid.UUID,
    payload: GenerateAssetsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    campaign = await get_owned_or_404(db, DistributionCampaign, campaign_id, user.id)
    return await service.generate_assets(
        db,
        orchestrator,
        campaign,
        payload.source_segment,
        payload.source_transcript_excerpt,
        payload.platforms,
    )
