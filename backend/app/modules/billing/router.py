import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.billing import service
from app.modules.billing.entitlement import PLAN_LIMITS, get_organization_for_user
from app.modules.billing.models import Organization, OrganizationMember, OrganizationRole
from app.modules.billing.providers.base import PaymentProviderNotConfiguredError
from app.modules.billing.schemas import (
    CheckoutOut,
    CheckoutRequest,
    CreateOrganizationRequest,
    InviteMemberRequest,
    MemberOut,
    OrganizationOut,
    SubscriptionOut,
    WhiteLabelRequest,
)
from app.modules.users.models import User

router = APIRouter()


async def _get_current_organization(db: AsyncSession, user: User) -> Organization:
    org = await get_organization_for_user(db, user.id)
    if not org:
        raise NotFoundError("No organization found for this account")
    return org


async def _require_org_admin(db: AsyncSession, user: User, organization_id: uuid.UUID) -> None:
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if not membership or membership.role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN):
        raise ForbiddenError("Only an organization owner or admin can manage members")


@router.get("/me", response_model=OrganizationOut)
async def get_my_organization(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await _get_current_organization(db, user)


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
async def create_organization(
    payload: CreateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.create_team_organization(db, user.id, payload.name)


@router.get("/organizations/{organization_id}/members", response_model=list[MemberOut])
async def list_members(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_org_admin(db, user, organization_id)
    return await service.list_members(db, organization_id)


@router.post("/organizations/{organization_id}/members", response_model=MemberOut, status_code=201)
async def invite_member(
    organization_id: uuid.UUID,
    payload: InviteMemberRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_org_admin(db, user, organization_id)
    return await service.invite_member(db, organization_id, payload.user_id, payload.role)


@router.delete("/organizations/{organization_id}/members/{member_user_id}", status_code=204)
async def remove_member(
    organization_id: uuid.UUID,
    member_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_org_admin(db, user, organization_id)
    await service.remove_member(db, organization_id, member_user_id)


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    org = await _get_current_organization(db, user)
    subscription = await service.get_subscription(db, org.id)
    if not subscription:
        raise NotFoundError("No subscription found for this organization")
    return subscription


@router.post("/checkout", response_model=CheckoutOut)
async def create_checkout(
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    org = await _get_current_organization(db, user)
    try:
        session = await service.start_checkout(db, org.id, payload.plan, payload.success_url)
    except PaymentProviderNotConfiguredError as exc:
        raise ValidationError(str(exc)) from exc
    return CheckoutOut(checkout_url=session.checkout_url, external_session_id=session.external_session_id)


@router.get("/plans")
async def list_plans():
    """Static plan/limit matrix -- lets the frontend render an accurate
    pricing/comparison table without hardcoding limits that could drift
    from entitlement.PLAN_LIMITS."""
    return {plan.value: limits for plan, limits in PLAN_LIMITS.items()}


@router.put("/organizations/{organization_id}/white-label", response_model=OrganizationOut)
async def set_white_label(
    organization_id: uuid.UUID,
    payload: WhiteLabelRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_org_admin(db, user, organization_id)
    org = await db.get(Organization, organization_id)
    if not org:
        raise NotFoundError("Organization not found")
    return await service.set_white_label(db, org, payload.enabled, payload.brand_name)
