import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.billing.models import OrganizationRole, Plan, SubscriptionStatus


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    plan: Plan
    is_white_label: bool
    white_label_brand_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: OrganizationRole
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: OrganizationRole = OrganizationRole.MEMBER


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    plan: Plan
    status: SubscriptionStatus
    payment_provider: str
    current_period_end: datetime | None

    model_config = {"from_attributes": True}


class CheckoutRequest(BaseModel):
    plan: Plan
    success_url: str = Field(min_length=1, max_length=2000)


class CheckoutOut(BaseModel):
    checkout_url: str
    external_session_id: str


class WhiteLabelRequest(BaseModel):
    enabled: bool
    brand_name: str | None = Field(default=None, max_length=200)
