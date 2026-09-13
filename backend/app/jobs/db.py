"""Celery-worker-specific async DB session factory.

Each Celery task runs its own `asyncio.run()` call (see `_run()` in
tasks.py), which creates and tears down a brand-new event loop per task.
`app.db.session.engine` uses SQLAlchemy's default pooled engine, which is
correct and desired for the FastAPI process (one event loop, alive for the
whole process lifetime) — but asyncpg connection objects hold event-loop-
bound internals (locks/futures) that cannot be reused once their owning
loop is closed. Reusing the FastAPI-style pooled engine from a Celery
worker intermittently hands back a connection created under a now-closed
loop, raising `RuntimeError: Task ... attached to a different loop`.

This module gives worker tasks their own engine configured with
`NullPool`: every checkout opens a fresh connection bound to the current
(correct) event loop and it is discarded — never pooled — when the
session closes. Slightly more connection overhead per task; Celery's task
volume never approaches request-per-second traffic, so this is the right
trade-off over the alternative (disposing the shared pool on every task,
which would also break FastAPI's own pooled usage if they shared an
engine instance).
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


def worker_engine_kwargs(database_url: str) -> dict:
    """SQLite (used only in tests) has no cross-event-loop connection
    identity problem and doesn't support NullPool the same way — real
    deployments (Postgres) always get NullPool."""
    return {} if database_url.startswith("sqlite") else {"poolclass": NullPool}


worker_engine = create_async_engine(settings.database_url, **worker_engine_kwargs(settings.database_url))

WorkerSessionLocal = async_sessionmaker(bind=worker_engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def worker_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with WorkerSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
