import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.scripts import service
from app.modules.scripts.models import Script
from app.modules.scripts.schemas import GenerateScriptRequest, ScriptOut
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[ScriptOut])
async def list_scripts(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_scripts(db, user.id)


@router.post("/generate", response_model=ScriptOut)
async def generate_script(
    payload: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    return await service.generate_script(
        db, orchestrator, user.id, payload.title, payload.topic_id, payload.format, payload.key_points
    )


@router.post("/{script_id}/versions", response_model=ScriptOut)
async def add_version(
    script_id: uuid.UUID,
    key_points: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_orchestrator),
):
    script = await get_owned_or_404(db, Script, script_id, user.id)
    key_points = key_points or []
    return await service.add_script_version(db, orchestrator, script, key_points)
