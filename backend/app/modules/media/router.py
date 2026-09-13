from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.auth.dependencies import require_editor
from app.modules.media import service
from app.modules.media.models import MediaPurpose
from app.modules.media.schemas import MediaAssetOut
from app.modules.users.models import User

router = APIRouter()


@router.post("/upload", response_model=MediaAssetOut, status_code=201)
async def upload_media(
    purpose: MediaPurpose = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """The only way a real video/thumbnail file enters CreatorOS today.
    Streamed to disk in bounded chunks -- never fully buffered in memory --
    with extension/size validation. Feed the returned asset's id into
    POST /publishing/runs (video_file_path) to actually publish it."""
    asset = await service.save_upload(db, user.id, purpose, file)
    out = MediaAssetOut.model_validate(asset)
    out.local_path = service.local_path_for(asset)
    return out
