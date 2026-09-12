import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.topics import service
from app.modules.topics.models import Topic
from app.modules.topics.schemas import CreateTopicRequest, OpportunityOut, TopicOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[TopicOut])
async def list_topics(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_topics(db, user.id)


@router.post("", response_model=TopicOut, status_code=201)
async def create_topic(
    payload: CreateTopicRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.create_topic(
        db, user.id, payload.title, payload.description, payload.trend_id
    )


@router.post("/{topic_id}/opportunity", response_model=OpportunityOut)
async def compute_opportunity(
    topic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    topic = await get_owned_or_404(db, Topic, topic_id, user.id)
    return await service.compute_opportunity(db, topic)
