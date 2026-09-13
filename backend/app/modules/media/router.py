import os
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.media import service
from app.modules.media.models import MediaAsset, MediaPurpose
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


@router.get("/{asset_id}")
async def download_media(
    asset_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Lets a creator preview an uploaded source video or a rendered
    Short before deciding whether to approve/publish it -- the pipeline's
    own 'preview' step needs a real way to fetch the bytes, not just an
    id. Ownership-checked like every other MediaAsset access; never
    trusts a client-supplied path since there isn't one here at all."""
    asset = await get_owned_or_404(db, MediaAsset, asset_id, user.id)
    path = service.local_path_for(asset)
    if not path or not os.path.isfile(path):
        raise NotFoundError("Media file is not available")
    return FileResponse(path, media_type=asset.content_type, filename=asset.original_filename)
