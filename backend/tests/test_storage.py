"""The production audit found a creatoros_storage Docker volume mounted
but nothing in the codebase ever writing to it -- no real storage layer
existed. These test the real LocalStorageBackend (default) plus the S3
backend's honest CONFIGURATION_REQUIRED behavior when unconfigured."""
import os

import pytest

from app.core.config import Settings
from app.core.storage import (
    LocalStorageBackend,
    S3StorageBackend,
    StorageNotConfiguredError,
    generate_key,
    get_storage_backend,
)


@pytest.mark.asyncio
async def test_local_backend_saves_and_reads_back_a_real_file(tmp_path):
    backend = LocalStorageBackend(str(tmp_path / "uploads"))
    source = tmp_path / "incoming.mp4"
    source.write_bytes(b"video bytes")

    stored = await backend.save("video/u1/abc.mp4", str(source))

    assert stored.backend == "local"
    assert stored.size_bytes == len(b"video bytes")
    resolved = backend.resolve_local_path("video/u1/abc.mp4")
    assert os.path.isfile(resolved)
    assert open(resolved, "rb").read() == b"video bytes"
    assert not os.path.isfile(source)  # save() moves, never copies-and-leaves-a-duplicate


@pytest.mark.asyncio
async def test_local_backend_delete_removes_the_file(tmp_path):
    backend = LocalStorageBackend(str(tmp_path / "uploads"))
    source = tmp_path / "incoming.mp4"
    source.write_bytes(b"x")
    await backend.save("video/u1/abc.mp4", str(source))

    await backend.delete("video/u1/abc.mp4")

    assert not os.path.isfile(backend.resolve_local_path("video/u1/abc.mp4"))


def test_local_backend_refuses_path_traversal(tmp_path):
    backend = LocalStorageBackend(str(tmp_path / "uploads"))
    with pytest.raises(Exception):
        backend._full_path("../../etc/passwd")


def test_s3_backend_reports_configuration_required_when_unconfigured():
    settings = Settings(storage_backend="s3", s3_bucket="", aws_access_key_id="", aws_secret_access_key="")
    with pytest.raises(StorageNotConfiguredError):
        S3StorageBackend(settings)


def test_get_storage_backend_defaults_to_local(tmp_path):
    settings = Settings(storage_backend="local", storage_local_path=str(tmp_path / "uploads"))
    backend = get_storage_backend(settings)
    assert backend.name == "local"


def test_generate_key_is_namespaced_by_owner_and_purpose():
    import uuid

    key = generate_key(uuid.UUID(int=1), "video", ".mp4")
    assert key.startswith("video/00000000-0000-0000-0000-000000000001/")
    assert key.endswith(".mp4")
