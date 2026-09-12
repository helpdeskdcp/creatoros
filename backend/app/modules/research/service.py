import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.research.models import ResearchProject, ResearchSource, SourceCredibility


async def create_project(
    db: AsyncSession, owner_user_id: uuid.UUID, title: str, topic_id: uuid.UUID | None
) -> ResearchProject:
    project = ResearchProject(owner_user_id=owner_user_id, title=title, topic_id=topic_id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def list_projects(db: AsyncSession, owner_user_id: uuid.UUID) -> list[ResearchProject]:
    result = await db.scalars(
        select(ResearchProject)
        .where(ResearchProject.owner_user_id == owner_user_id)
        .order_by(ResearchProject.created_at.desc())
    )
    return list(result)


async def add_source(
    db: AsyncSession,
    project_id: uuid.UUID,
    url: str,
    title: str | None,
    claim: str | None,
    citation: str | None,
    added_by_ai: bool = False,
) -> ResearchSource:
    """A human-submitted source starts unverified pending review; an
    AI-suggested source always starts needs_review — the AI Quality Rule
    forbids ever marking a source 'verified' automatically."""
    source = ResearchSource(
        research_project_id=project_id,
        url=url,
        title=title,
        claim=claim,
        citation=citation,
        added_by_ai=added_by_ai,
        credibility=SourceCredibility.NEEDS_REVIEW if added_by_ai else SourceCredibility.UNVERIFIED,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def list_sources(db: AsyncSession, project_id: uuid.UUID) -> list[ResearchSource]:
    result = await db.scalars(
        select(ResearchSource).where(ResearchSource.research_project_id == project_id)
    )
    return list(result)


async def set_source_credibility(
    db: AsyncSession, source_id: uuid.UUID, credibility: SourceCredibility
) -> ResearchSource:
    source = await db.get(ResearchSource, source_id)
    if not source:
        raise NotFoundError("Research source not found")
    source.credibility = credibility
    if credibility == SourceCredibility.VERIFIED:
        source.verified_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(source)
    return source
