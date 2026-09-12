"""Platform-specific asset generation. Extends the Shorts engine's idea of
"one source video, many derivatives" across social platforms — never
duplicates the source media, only generates text/plan-level assets per
platform (see docs/operations.md: VPS Storage Optimization)."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIOrchestrator
from app.modules.distribution.models import DistributionAsset, DistributionCampaign
from app.modules.distribution.schemas import GeneratedAssetsResponse

SYSTEM_PROMPT = (
    "You are CreatorOS's Social Distribution Engine. Given an excerpt from a "
    "YouTube video's transcript, generate ONE platform-appropriate derivative "
    "asset per requested platform — never the same content copy-pasted "
    "across platforms. Instagram: visual-first, short caption. X: concise, "
    "thread-worthy. Facebook: context-rich. LinkedIn: professional/value "
    "framing. Each needs a hook, caption, CTA, and short title."
)


async def create_campaign(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    name: str,
    source_video_id: uuid.UUID | None,
    starts_at,
    ends_at,
) -> DistributionCampaign:
    campaign = DistributionCampaign(
        owner_user_id=owner_user_id,
        name=name,
        source_video_id=source_video_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def list_campaigns(db: AsyncSession, owner_user_id: uuid.UUID) -> list[DistributionCampaign]:
    result = await db.scalars(
        select(DistributionCampaign)
        .where(DistributionCampaign.owner_user_id == owner_user_id)
        .order_by(DistributionCampaign.created_at.desc())
    )
    return list(result)


async def generate_assets(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    campaign: DistributionCampaign,
    source_segment: str | None,
    transcript_excerpt: str,
    platforms: list,
) -> list[DistributionAsset]:
    user_prompt = (
        f"Transcript excerpt: {transcript_excerpt}\n"
        f"Generate one asset for each of these platforms: {', '.join(p.value for p in platforms)}"
    )
    result: GeneratedAssetsResponse = await orchestrator.generate_structured(
        task="generate_distribution_assets",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=GeneratedAssetsResponse,
    )

    assets: list[DistributionAsset] = []
    for g in result.assets:
        asset = DistributionAsset(
            campaign_id=campaign.id,
            source_video_id=campaign.source_video_id,
            source_segment=source_segment,
            platform=g.platform,
            format=g.format,
            hook=g.hook,
            caption=g.caption,
            cta=g.cta,
            title=g.title,
        )
        db.add(asset)
        assets.append(asset)

    await db.commit()
    for a in assets:
        await db.refresh(a)
    return assets


async def list_assets(db: AsyncSession, campaign_id: uuid.UUID) -> list[DistributionAsset]:
    result = await db.scalars(
        select(DistributionAsset).where(DistributionAsset.campaign_id == campaign_id)
    )
    return list(result)
