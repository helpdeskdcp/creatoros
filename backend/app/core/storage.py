"""Object storage abstraction. The production audit found a creatoros_storage
Docker volume mounted but nothing in the codebase ever writing to it --
CreatorOS had no real storage layer at all, only an unused mount point.

StorageBackend is the single interface everything (media uploads, and
eventually rendered clips) goes through -- the same pattern already
established for AIProvider and YouTubeProvider: one interface, swappable
real implementations, nothing above this layer imports boto3 or touches a
raw filesystem path directly.
"""
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import Settings, get_settings


class StorageError(Exception):
    """Raised on a real storage failure (disk full, S3 auth/network error).
    Never swallowed -- a failed save must never be reported as success."""


class StorageNotConfiguredError(StorageError):
    """The selected backend requires configuration that is not present.
    Distinct from StorageError so callers can surface CONFIGURATION_REQUIRED
    rather than a generic failure."""


@dataclass
class StoredObject:
    key: str
    size_bytes: int
    backend: str


class StorageBackend(ABC):
    name: str

    @abstractmethod
    async def save(self, key: str, local_source_path: str) -> StoredObject:
        """Persists the file already written at local_source_path under
        `key`. Callers write the incoming upload to a local temp path first
        (streamed, never fully buffered in memory) then hand it here --
        this keeps the interface identical whether the destination is local
        disk (a simple move) or S3 (a real upload)."""

    @abstractmethod
    def resolve_local_path(self, key: str) -> str:
        """Returns a filesystem path execute_run()/ffmpeg can read `key`
        from. For S3, this must download first (not implemented here yet --
        CreatorOS's only current consumer, publishing execute_run, always
        uses the local backend's own key directly today)."""

    @abstractmethod
    async def delete(self, key: str) -> None: ...


class LocalStorageBackend(StorageBackend):
    name = "local"

    def __init__(self, base_path: str) -> None:
        self._base_path = base_path
        os.makedirs(self._base_path, exist_ok=True)

    def _full_path(self, key: str) -> str:
        # Defense against path traversal: key is always a value THIS module
        # generated (see generate_key()), never taken from user input
        # directly, but this check stays cheap insurance regardless.
        full = os.path.normpath(os.path.join(self._base_path, key))
        if not full.startswith(os.path.normpath(self._base_path) + os.sep):
            raise StorageError(f"Refused to store outside base path: {key}")
        return full

    async def save(self, key: str, local_source_path: str) -> StoredObject:
        dest = self._full_path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(local_source_path, dest)
        return StoredObject(key=key, size_bytes=os.path.getsize(dest), backend=self.name)

    def resolve_local_path(self, key: str) -> str:
        return self._full_path(key)

    async def delete(self, key: str) -> None:
        path = self._full_path(key)
        if os.path.isfile(path):
            os.remove(path)


class S3StorageBackend(StorageBackend):
    name = "s3"

    def __init__(self, settings: Settings) -> None:
        if not settings.s3_configured:
            raise StorageNotConfiguredError(
                "storage_backend is 's3' but S3_BUCKET/AWS credentials are not set"
            )
        import boto3  # deferred: never imported/required for the local backend

        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    async def save(self, key: str, local_source_path: str) -> StoredObject:
        try:
            self._client.upload_file(local_source_path, self._bucket, key)
        except Exception as exc:  # noqa: BLE001 -- boto3 raises many distinct exception types
            raise StorageError(f"S3 upload failed: {exc}") from exc
        return StoredObject(key=key, size_bytes=os.path.getsize(local_source_path), backend=self.name)

    def resolve_local_path(self, key: str) -> str:
        raise NotImplementedError(
            "S3StorageBackend has no local path for a stored key yet -- "
            "no current caller needs to read a key back locally"
        )

    async def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"S3 delete failed: {exc}") from exc


def generate_key(owner_user_id: uuid.UUID, purpose: str, extension: str) -> str:
    return f"{purpose}/{owner_user_id}/{uuid.uuid4().hex}{extension}"


def get_storage_backend(settings: Settings | None = None) -> StorageBackend:
    settings = settings or get_settings()
    if settings.storage_backend == "s3":
        return S3StorageBackend(settings)
    return LocalStorageBackend(settings.storage_local_path)
