import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.research import service
from app.modules.research.models import ResearchProject
from app.modules.research.schemas import (
    AddSourceRequest,
    CreateResearchProjectRequest,
    ResearchProjectOut,
    ResearchSourceOut,
    VerifySourceRequest,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[ResearchProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_projects(db, user.id)


@router.post("", response_model=ResearchProjectOut, status_code=201)
async def create_project(
    payload: CreateResearchProjectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.create_project(db, user.id, payload.title, payload.topic_id)


@router.get("/{project_id}/sources", response_model=list[ResearchSourceOut])
async def list_sources(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_owned_or_404(db, ResearchProject, project_id, user.id)
    return await service.list_sources(db, project_id)


@router.post("/{project_id}/sources", response_model=ResearchSourceOut, status_code=201)
async def add_source(
    project_id: uuid.UUID,
    payload: AddSourceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_owned_or_404(db, ResearchProject, project_id, user.id)
    return await service.add_source(
        db, project_id, payload.url, payload.title, payload.claim, payload.citation
    )


@router.patch("/sources/{source_id}/credibility", response_model=ResearchSourceOut)
async def set_credibility(
    source_id: uuid.UUID,
    payload: VerifySourceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.set_source_credibility(db, source_id, payload.credibility)
