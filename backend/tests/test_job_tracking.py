"""Jobs-table observability: production audit found `_start_job`/
`_finish_job` existed but only one task (youtube_sync) ever called them --
the jobs table had zero rows across the whole live database. _tracked_job
wraps every beat-scheduled task uniformly; these tests verify it actually
records SUCCEEDED and FAILED runs with real start/finish timestamps.

Uses its own throwaway sqlite engine (monkeypatched in place of the
process-global WorkerSessionLocal) rather than the standard db_session
fixture -- WorkerSessionLocal is a module-level singleton bound to
DATABASE_URL, separate from conftest's per-test db_engine fixture, so
exercising the real one here needs its own schema instead."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import models_registry
from app.jobs.models import Job, JobStatus


@pytest.fixture
async def worker_session_local(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(models_registry.Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.jobs.tasks.WorkerSessionLocal", session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_tracked_job_records_success(worker_session_local):
    from app.jobs.tasks import _tracked_job

    async with _tracked_job("test_job_type") as result:
        result["thing"] = 42

    async with worker_session_local() as db:
        job = await db.scalar(select(Job).where(Job.job_type == "test_job_type"))
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.finished_at >= job.started_at
    assert "42" in job.result_json


@pytest.mark.asyncio
async def test_tracked_job_records_failure_and_reraises(worker_session_local):
    from app.jobs.tasks import _tracked_job

    with pytest.raises(RuntimeError, match="boom"):
        async with _tracked_job("test_job_type_fail") as result:
            result["progress"] = "partial"
            raise RuntimeError("boom")

    async with worker_session_local() as db:
        job = await db.scalar(select(Job).where(Job.job_type == "test_job_type_fail"))
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert "boom" in job.error
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_tracked_job_status_is_running_during_execution(worker_session_local):
    from app.jobs.tasks import _tracked_job

    async with _tracked_job("test_job_type_running") as _result:
        async with worker_session_local() as db:
            job = await db.scalar(select(Job).where(Job.job_type == "test_job_type_running"))
        assert job.status == JobStatus.RUNNING
        assert job.finished_at is None
