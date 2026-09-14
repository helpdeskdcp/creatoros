"""Phase 7: multi-tenant billing/teams/agency architecture. Covers the
things that were previously entirely absent -- every user implicitly
getting an organization on registration, a centralized plan-limit
matrix actually being enforced against a real endpoint (channel
connection), team invite/remove with role checks, and checkout honestly
reporting CONFIGURATION_REQUIRED rather than fabricating a successful
payment since no PaymentProvider is configured in this environment."""
import uuid

import pytest

from app.core.errors import ForbiddenError
from app.modules.billing import service as billing_service
from app.modules.billing.entitlement import enforce_limit, get_organization_for_user
from app.modules.billing.models import OrganizationRole, Plan, SubscriptionStatus
from app.modules.billing.providers.base import PaymentProviderNotConfiguredError
from app.modules.users.models import User, UserRole


async def _register(client, email: str) -> tuple[str, uuid.UUID]:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_registration_creates_personal_organization(client, db_session):
    token, user_id = await _register(client, "org-owner@example.com")

    org = await get_organization_for_user(db_session, user_id)
    assert org is not None
    assert org.plan == Plan.FREE

    resp = await client.get("/api/v1/billing/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == str(org.id)


@pytest.mark.asyncio
async def test_registration_is_idempotent_about_organization_creation(db_session):
    user = User(email="idem@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    org1 = await billing_service.ensure_personal_organization(db_session, user.id)
    org2 = await billing_service.ensure_personal_organization(db_session, user.id)

    assert org1.id == org2.id


@pytest.mark.asyncio
async def test_free_plan_channel_limit_enforced_via_real_endpoint(client, db_session):
    token, _ = await _register(client, "limit-owner@example.com")

    first = await client.post(
        "/api/v1/channels", json={"youtube_channel_id": "UC_first_channel"}, headers=_auth(token)
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/channels", json={"youtube_channel_id": "UC_second_channel"}, headers=_auth(token)
    )
    assert second.status_code == 403
    assert "max_channels" in second.json()["error"]["message"]


@pytest.mark.asyncio
async def test_enforce_limit_treats_userless_org_as_free_plan(db_session):
    user = User(email="noorg@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    with pytest.raises(ForbiddenError):
        await enforce_limit(db_session, user_id=user.id, feature="max_channels", current_count=1)


@pytest.mark.asyncio
async def test_create_team_organization_moves_owner_and_sets_role(db_session):
    user = User(email="agency-owner@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    personal_org = await billing_service.ensure_personal_organization(db_session, user.id)
    team_org = await billing_service.create_team_organization(db_session, user.id, "My Agency")

    assert team_org.id != personal_org.id
    current_org = await get_organization_for_user(db_session, user.id)
    assert current_org.id == team_org.id

    members = await billing_service.list_members(db_session, team_org.id)
    assert len(members) == 1
    assert members[0].role == OrganizationRole.OWNER


@pytest.mark.asyncio
async def test_invite_member_respects_team_size_limit(db_session):
    owner = User(email="team-owner@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)
    org = await billing_service.create_team_organization(db_session, owner.id, "Small Team")
    # FREE plan max_team_members == 1 -- the owner already fills that slot.

    invitee = User(email="invitee@example.com", hashed_password="x", role=UserRole.VIEWER)
    db_session.add(invitee)
    await db_session.commit()
    await db_session.refresh(invitee)

    with pytest.raises(ForbiddenError):
        await billing_service.invite_member(db_session, org.id, invitee.id, OrganizationRole.MEMBER)


@pytest.mark.asyncio
async def test_invite_then_remove_member(db_session):
    owner = User(email="team-owner2@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)
    org = await billing_service.create_team_organization(db_session, owner.id, "Pro Team")
    org.plan = Plan.PRO
    await db_session.commit()

    invitee = User(email="invitee2@example.com", hashed_password="x", role=UserRole.VIEWER)
    db_session.add(invitee)
    await db_session.commit()
    await db_session.refresh(invitee)

    member = await billing_service.invite_member(db_session, org.id, invitee.id, OrganizationRole.MEMBER)
    assert member.role == OrganizationRole.MEMBER

    members = await billing_service.list_members(db_session, org.id)
    assert len(members) == 2

    await billing_service.remove_member(db_session, org.id, invitee.id)
    members = await billing_service.list_members(db_session, org.id)
    assert len(members) == 1


@pytest.mark.asyncio
async def test_cannot_remove_organization_owner(db_session):
    owner = User(email="team-owner3@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)
    org = await billing_service.create_team_organization(db_session, owner.id, "Solo Org")

    from app.core.errors import ConflictError

    with pytest.raises(ConflictError):
        await billing_service.remove_member(db_session, org.id, owner.id)


@pytest.mark.asyncio
async def test_subscription_defaults_to_configuration_required(db_session):
    user = User(email="sub-check@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    org = await billing_service.ensure_personal_organization(db_session, user.id)

    subscription = await billing_service.get_subscription(db_session, org.id)
    assert subscription is not None
    assert subscription.status == SubscriptionStatus.CONFIGURATION_REQUIRED
    assert subscription.payment_provider == "none"


@pytest.mark.asyncio
async def test_checkout_raises_not_configured_without_a_real_payment_provider(db_session):
    user = User(email="checkout@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    org = await billing_service.ensure_personal_organization(db_session, user.id)

    with pytest.raises(PaymentProviderNotConfiguredError):
        await billing_service.start_checkout(db_session, org.id, Plan.PRO, "https://app.example.com/done")


@pytest.mark.asyncio
async def test_checkout_endpoint_returns_400_not_500(client, db_session):
    token, _ = await _register(client, "checkout-api@example.com")
    resp = await client.post(
        "/api/v1/billing/checkout",
        json={"plan": "PRO", "success_url": "https://app.example.com/done"},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "no payment provider is configured" in resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_white_label_forbidden_on_free_plan(db_session):
    user = User(email="wl-free@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    org = await billing_service.ensure_personal_organization(db_session, user.id)

    with pytest.raises(ForbiddenError):
        await billing_service.set_white_label(db_session, org, enabled=True, brand_name="Acme")


@pytest.mark.asyncio
async def test_white_label_allowed_on_agency_plan(db_session):
    user = User(email="wl-agency@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    org = await billing_service.ensure_personal_organization(db_session, user.id)
    org.plan = Plan.AGENCY
    await db_session.commit()

    updated = await billing_service.set_white_label(db_session, org, enabled=True, brand_name="Acme")
    assert updated.is_white_label is True
    assert updated.white_label_brand_name == "Acme"


@pytest.mark.asyncio
async def test_plans_endpoint_exposes_limit_matrix(client):
    resp = await client.get("/api/v1/billing/plans")
    assert resp.status_code == 200
    body = resp.json()
    assert body["FREE"]["max_channels"] == 1
    assert body["ENTERPRISE"]["max_channels"] == -1


@pytest.mark.asyncio
async def test_non_admin_member_cannot_invite(client, db_session):
    owner = User(email="rbac-owner@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)
    org = await billing_service.create_team_organization(db_session, owner.id, "RBAC Org")
    org.plan = Plan.PRO
    await db_session.commit()

    member_user = User(email="rbac-member@example.com", hashed_password="x", role=UserRole.VIEWER)
    db_session.add(member_user)
    await db_session.commit()
    await db_session.refresh(member_user)
    await billing_service.invite_member(db_session, org.id, member_user.id, OrganizationRole.MEMBER)

    from app.core.security import create_jwt

    token, _ = create_jwt(subject=str(member_user.id), token_type="access")
    other_user = User(email="rbac-target@example.com", hashed_password="x", role=UserRole.VIEWER)
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    resp = await client.post(
        f"/api/v1/billing/organizations/{org.id}/members",
        json={"user_id": str(other_user.id), "role": "MEMBER"},
        headers=_auth(token),
    )
    assert resp.status_code == 403
