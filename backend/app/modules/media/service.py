"""Real, validated file upload -- streamed to disk, never fully buffered in
memory, with a hard size ceiling enforced against actual bytes received
(not a trusted Content-Length header). This is the one place a source
video file can enter CreatorOS today; publishing.execute_run() reads the
resulting local path back out via the same storage backend.
"""
import os
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.storage import generate_key, get_storage_backend
from app.modules.media.models import MediaAsset, MediaPurpose

_ALLOWED_BY_PURPOSE: dict[MediaPurpose, dict[str, str]] = {
    MediaPurpose.VIDEO: {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"},
    MediaPurpose.THUMBNAIL: {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"},
}
_MAX_BYTES_BY_PURPOSE = {
    MediaPurpose.VIDEO: 20 * 1024 * 1024 * 1024,  # 20GB, YouTube's own ceiling
    MediaPurpose.THUMBNAIL: 10 * 1024 * 1024,  # YouTube thumbnail limit
}
_CHUNK_SIZE = 1024 * 1024  # 1MB


async def save_upload(
    db: AsyncSession, owner_user_id: uuid.UUID, purpose: MediaPurpose, upload: UploadFile
) -> MediaAsset:
    allowed = _ALLOWED_BY_PURPOSE[purpose]
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in allowed:
        raise ValidationError(f"Unsupported file type '{ext}' for {purpose.value}: allowed {sorted(allowed)}")

    max_bytes = _MAX_BYTES_BY_PURPOSE[purpose]
    settings = get_settings()
    tmp_dir = os.path.join(settings.storage_local_path, "_tmp_incoming")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, uuid.uuid4().hex)

    written = 0
    try:
        with open(tmp_path, "wb") as f:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValidationError(
                        f"File exceeds the {max_bytes} byte limit for {purpose.value}"
                    )
                f.write(chunk)
        if written == 0:
            raise ValidationError("Uploaded file is empty")

        storage = get_storage_backend(settings)
        key = generate_key(owner_user_id, purpose.value.lower(), ext)
        stored = await storage.save(key, tmp_path)  # moves/uploads tmp_path -> its final location
    finally:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)  # no-op if save() already moved it (local backend)

    asset = MediaAsset(
        owner_user_id=owner_user_id,
        purpose=purpose,
        storage_backend=stored.backend,
        storage_key=stored.key,
        original_filename=upload.filename or "upload",
        content_type=allowed[ext],
        size_bytes=stored.size_bytes,
        created_at=datetime.now(UTC),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def save_local_file(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    purpose: MediaPurpose,
    local_path: str,
    *,
    original_filename: str,
    content_type: str,
) -> MediaAsset:
    """For a file CreatorOS itself already produced and validated on disk
    (a rendered Short, for example) -- unlike save_upload(), there is no
    untrusted client stream to bound/validate here, since the caller
    (shorts.service.render_candidate) is the one that generated the file
    via ffmpeg in the first place. Still goes through the same
    StorageBackend so a rendered clip lives wherever uploads do (and, if
    S3 is configured, benefits from the same persistence)."""
    settings = get_settings()
    storage = get_storage_backend(settings)
    ext = os.path.splitext(local_path)[1].lower()
    key = generate_key(owner_user_id, purpose.value.lower(), ext)
    stored = await storage.save(key, local_path)  # moves local_path -> final location

    asset = MediaAsset(
        owner_user_id=owner_user_id,
        purpose=purpose,
        storage_backend=stored.backend,
        storage_key=stored.key,
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        created_at=datetime.now(UTC),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


def local_path_for(asset: MediaAsset) -> str | None:
    """Best-effort local filesystem path for an asset -- publishing.
    execute_run() needs a real path to hand to the YouTubeProvider. Only
    meaningful for the local backend today (see StorageBackend.
    resolve_local_path's S3 docstring)."""
    if asset.storage_backend != "local":
        return None
    settings = get_settings()
    from app.core.storage import LocalStorageBackend

    backend = LocalStorageBackend(settings.storage_local_path)
    return backend.resolve_local_path(asset.storage_key)


_PEXELS_EXT_BY_PURPOSE: dict[MediaPurpose, tuple[str, str]] = {
    MediaPurpose.VIDEO: (".mp4", "video/mp4"),
    MediaPurpose.THUMBNAIL: (".jpg", "image/jpeg"),
}


async def import_from_pexels(
    db: AsyncSession, owner_user_id: uuid.UUID, purpose: MediaPurpose, download_url: str, *, filename_hint: str
) -> MediaAsset:
    """Downloads a Pexels-hosted photo/video's real bytes and stores it as
    a normal MediaAsset -- from here on it's indistinguishable from a
    directly-uploaded file (usable in publishing/shorts/thumbnails exactly
    the same way). See app.modules.media.pexels for the actual HTTP call."""
    from app.modules.media import pexels

    ext, content_type = _PEXELS_EXT_BY_PURPOSE[purpose]
    settings = get_settings()
    tmp_dir = os.path.join(settings.storage_local_path, "_tmp_incoming")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{ext}")

    try:
        written = await pexels.download_to_file(download_url, tmp_path)
        if written == 0:
            raise ValidationError("Pexels download returned an empty file")
        return await save_local_file(
            db, owner_user_id, purpose, tmp_path,
            original_filename=f"{filename_hint}{ext}", content_type=content_type,
        )
    finally:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)  # no-op if save_local_file already moved it (local backend)
