import os
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.crud import get_owned_or_404
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.media import pexels, service
from app.modules.media.models import MediaAsset, MediaPurpose
from app.modules.media.schemas import MediaAssetOut, PexelsImportRequest, PexelsPhotoOut, PexelsVideoOut
from app.modules.users.models import User

router = APIRouter()


def _get_settings() -> Settings:
    return get_settings()


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


@router.get("/pexels/photos", response_model=list[PexelsPhotoOut])
async def search_pexels_photos(
    query: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(_get_settings),
):
    """Free stock photo search -- source images for image-to-video (feed
    a result's download_url straight into a video job's
    input_image_urls, no import step needed) or thumbnail backgrounds."""
    return await pexels.search_photos(settings, query)


@router.get("/pexels/videos", response_model=list[PexelsVideoOut])
async def search_pexels_videos(
    query: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(_get_settings),
):
    """Free stock video search -- B-roll candidates."""
    return await pexels.search_videos(settings, query)


@router.post("/pexels/import", response_model=MediaAssetOut, status_code=201)
async def import_pexels_media(
    payload: PexelsImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Downloads a chosen search result's real bytes and stores it as a
    normal MediaAsset -- for B-roll (purpose=VIDEO) or a thumbnail source
    image (purpose=THUMBNAIL). From here on it's usable exactly like any
    directly-uploaded file (see POST /media/upload)."""
    asset = await service.import_from_pexels(
        db, user.id, payload.purpose, payload.download_url, filename_hint=payload.filename_hint,
    )
    out = MediaAssetOut.model_validate(asset)
    out.local_path = service.local_path_for(asset)
    return out
