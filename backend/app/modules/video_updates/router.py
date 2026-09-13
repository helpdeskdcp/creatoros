import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.users.models import User
from app.modules.video_updates import service
from app.modules.video_updates.schemas import ProposeVideoUpdateRequest, VideoUpdateProposalOut

router = APIRouter()


@router.get("", response_model=list[VideoUpdateProposalOut])
async def list_proposals(
    video_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.list_proposals(db, user.id, video_id)


@router.post("", response_model=VideoUpdateProposalOut, status_code=201)
async def propose_update(
    payload: ProposeVideoUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await service.propose_update(
        db, user.id, payload.video_id, payload.field, payload.proposed_value,
        payload.reason, payload.evidence,
    )


@router.post("/{proposal_id}/approve", response_model=VideoUpdateProposalOut)
async def approve_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await service.approve_and_execute(db, proposal_id, user.id)


@router.post("/{proposal_id}/reject", response_model=VideoUpdateProposalOut)
async def reject_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await service.reject_proposal(db, proposal_id, user.id)


@router.post("/{proposal_id}/rollback", response_model=VideoUpdateProposalOut, status_code=201)
async def rollback_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    return await service.create_rollback(db, proposal_id, user.id)


@router.post("/{proposal_id}/measure-impact", response_model=VideoUpdateProposalOut)
async def measure_impact(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.measure_update_impact(db, proposal_id, user.id)
