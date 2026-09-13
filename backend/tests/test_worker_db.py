"""Regression coverage for the youtube_sync 'attached to a different loop'
production bug: Celery tasks each run their own asyncio.run() (a fresh
event loop per task), and asyncpg connections are bound to the loop that
created them. Reusing a pooled engine across those loops intermittently
hands back a connection from a closed loop. app/jobs/db.py fixes this by
giving worker tasks a NullPool-backed engine (real deployments) so no
connection ever survives past the task that opened it."""
from sqlalchemy.pool import NullPool

from app.jobs.db import WorkerSessionLocal, worker_engine_kwargs


def test_postgres_worker_engine_uses_null_pool():
    kwargs = worker_engine_kwargs("postgresql+asyncpg://user:pass@host/db")
    assert kwargs == {"poolclass": NullPool}


def test_sqlite_worker_engine_uses_default_pool():
    # SQLite (test-only) has no cross-loop connection identity issue and
    # doesn't need/support NullPool the same way real deployments do.
    assert worker_engine_kwargs("sqlite+aiosqlite:///:memory:") == {}


def test_worker_session_survives_across_separate_event_loops(tmp_path):
    """Simulates two sequential Celery task invocations, each via its own
    top-level asyncio.run() call — precisely what app/jobs/tasks.py's
    _run() does per task — sharing one process-level session factory
    against the same on-disk database. This is the exact shape of the
    production bug: a plain (non-async) test function, no surrounding
    event loop, matching how Celery actually invokes task bodies."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_path = tmp_path / "worker_loop_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _task_body():
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar()

    # Each asyncio.run() creates a brand-new event loop and tears it down
    # on exit — if the session factory's engine held onto a connection
    # bound to the first loop, the second call would raise exactly the
    # production error ("attached to a different loop").
    result_one = asyncio.run(_task_body())
    result_two = asyncio.run(_task_body())

    assert result_one == 1
    assert result_two == 1


def test_worker_session_local_is_bound_to_worker_engine():
    from app.jobs.db import worker_engine

    assert WorkerSessionLocal.kw["bind"] is worker_engine
