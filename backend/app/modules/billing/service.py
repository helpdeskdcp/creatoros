import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.modules.billing.entitlement import get_limit, get_organization_for_user
from app.modules.billing.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.modules.billing.providers import get_payment_provider
from app.modules.billing.providers.base import CheckoutSession


async def ensure_personal_organization(db: AsyncSession, user_id: uuid.UUID) -> Organization:
    """Every user gets an implicit FREE-plan organization -- this is what
    lets entitlement checks assume every user has exactly one
    organization, instead of every caller having to handle "no org yet"
    as a special case."""
    existing = await get_organization_for_user(db, user_id)
    if existing:
        return existing

    org = Organization(name="Personal", plan=Plan.FREE)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user_id, role=OrganizationRole.OWNER))
    db.add(Subscription(organization_id=org.id, plan=Plan.FREE, status=SubscriptionStatus.CONFIGURATION_REQUIRED))
    await db.commit()
    await db.refresh(org)
    return org


async def create_team_organization(db: AsyncSession, owner_user_id: uuid.UUID, name: str) -> Organization:
    """Explicit team/agency creation -- the owner is moved into the new
    organization as OWNER (a user belongs to exactly one organization at
    a time in this model, matching the unique constraint on
    OrganizationMember)."""
    existing_membership = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == owner_user_id)
    )
    if existing_membership:
        await db.delete(existing_membership)
        await db.flush()

    org = Organization(name=name, plan=Plan.FREE)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner_user_id, role=OrganizationRole.OWNER))
    db.add(Subscription(organization_id=org.id, plan=Plan.FREE, status=SubscriptionStatus.CONFIGURATION_REQUIRED))
    await db.commit()
    await db.refresh(org)
    return org


async def invite_member(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, role: OrganizationRole
) -> OrganizationMember:
    existing = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id
        )
    )
    if existing:
        raise ConflictError("This user is already a member of an organization")

    current_count = await db.scalar(
        select(func.count()).select_from(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id
        )
    )
    inviter_org = await db.get(Organization, organization_id)
    # enforce_limit (entitlement.py) is keyed by a USER's org membership;
    # here we already have the target org directly, so check its plan limit
    # inline rather than resolving membership a second time.
    limit = get_limit(inviter_org.plan, "max_team_members")
    if limit != -1 and current_count >= limit:
        raise ForbiddenError(
            f"Team member limit reached for the {inviter_org.plan.value} plan ({current_count}/{limit})"
        )

    member = OrganizationMember(organization_id=organization_id, user_id=user_id, role=role)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id
        )
    )
    if not member:
        raise NotFoundError("Membership not found")
    if member.role == OrganizationRole.OWNER:
        raise ConflictError("Cannot remove the organization owner")
    await db.delete(member)
    await db.commit()


async def list_members(db: AsyncSession, organization_id: uuid.UUID) -> list[OrganizationMember]:
    result = await db.scalars(
        select(OrganizationMember).where(OrganizationMember.organization_id == organization_id)
    )
    return list(result)


async def get_subscription(db: AsyncSession, organization_id: uuid.UUID) -> Subscription | None:
    return await db.scalar(select(Subscription).where(Subscription.organization_id == organization_id))


async def start_checkout(db: AsyncSession, organization_id: uuid.UUID, plan: Plan, success_url: str) -> CheckoutSession:
    """Delegates to whatever PaymentProvider is configured. With the
    default NullPaymentProvider this raises PaymentProviderNotConfiguredError
    -- never a fabricated successful checkout."""
    provider = get_payment_provider()
    return await provider.create_checkout_session(str(organization_id), plan.value, success_url)


async def set_white_label(db: AsyncSession, organization: Organization, enabled: bool, brand_name: str | None) -> Organization:
    if enabled and not get_limit(organization.plan, "white_label"):
        raise ForbiddenError(f"White-label is not available on the {organization.plan.value} plan")
    organization.is_white_label = enabled
    organization.white_label_brand_name = brand_name if enabled else None
    await db.commit()
    await db.refresh(organization)
    return organization
