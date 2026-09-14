from fastapi import APIRouter, Depends

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.modules.ai_chat import service
from app.modules.ai_chat.schemas import AIChatRequest, AIChatResponse
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter()


@router.post("/chat", response_model=AIChatResponse)
async def ai_chat(
    payload: AIChatRequest,
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    return await service.chat(orchestrator, payload)
