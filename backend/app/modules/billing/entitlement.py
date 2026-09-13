"""Centralized entitlement service -- the ONLY place plan limits are
defined. Every feature that needs a plan-gated limit calls
enforce_limit()/get_limit() here instead of hardcoding a number in its
own module; changing a plan's limits (or adding a plan) never requires
touching channels/competitors/experiments/etc.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.modules.billing.models import Organization, OrganizationMember, Plan

UNLIMITED = -1

PLAN_LIMITS: dict[Plan, dict[str, int | bool]] = {
    Plan.FREE: {
        "max_channels": 1, "max_team_members": 1, "max_competitors_tracked": 2,
        "white_label": False, "ai_generations_per_day": 20,
    },
    Plan.PRO: {
        "max_channels": 3, "max_team_members": 3, "max_competitors_tracked": 10,
        "white_label": False, "ai_generations_per_day": 200,
    },
    Plan.AGENCY: {
        "max_channels": 20, "max_team_members": 15, "max_competitors_tracked": 50,
        "white_label": True, "ai_generations_per_day": 2000,
    },
    Plan.ENTERPRISE: {
        "max_channels": UNLIMITED, "max_team_members": UNLIMITED, "max_competitors_tracked": UNLIMITED,
        "white_label": True, "ai_generations_per_day": UNLIMITED,
    },
}


def get_limit(plan: Plan, feature: str) -> int | bool:
    return PLAN_LIMITS[plan][feature]


async def get_organization_for_user(db: AsyncSession, user_id: uuid.UUID) -> Organization | None:
    membership = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == user_id)
    )
    if not membership:
        return None
    return await db.get(Organization, membership.organization_id)


async def enforce_limit(db: AsyncSession, user_id: uuid.UUID, feature: str, current_count: int) -> None:
    """Raises ForbiddenError if current_count is already at or beyond the
    caller's plan limit for `feature`. A user with no organization yet
    (shouldn't normally happen -- see service.ensure_personal_organization)
    is treated as FREE plan, never as unlimited."""
    org = await get_organization_for_user(db, user_id)
    plan = org.plan if org else Plan.FREE
    limit = get_limit(plan, feature)
    if limit == UNLIMITED:
        return
    if isinstance(limit, bool):
        if not limit:
            raise ForbiddenError(f"{feature} is not available on the {plan.value} plan")
        return
    if current_count >= limit:
        raise ForbiddenError(
            f"{feature} limit reached for the {plan.value} plan ({current_count}/{limit}). Upgrade to increase this."
        )
