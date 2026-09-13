"""Multi-tenant architecture: Organization is the billing/team boundary
(an individual creator gets one implicitly; an agency's organization can
hold many team members and, eventually, many managed creator accounts).
Nothing here fakes a payment -- Subscription.payment_provider is "none"
until a real PaymentProvider is configured, and stays that way honestly
rather than pretending a checkout succeeded.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Plan(str, enum.Enum):
    FREE = "FREE"
    PRO = "PRO"
    AGENCY = "AGENCY"
    ENTERPRISE = "ENTERPRISE"


class OrganizationRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    TRIALING = "TRIALING"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"
    # No payment provider configured -- distinct from CANCELED, which
    # implies a real subscription existed and ended.
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The billing/team boundary. Every user implicitly gets one on
    registration (see billing.service.ensure_personal_organization) so
    entitlement checks have exactly one code path whether or not the
    user has ever explicitly created or joined a team."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[Plan] = mapped_column(Enum(Plan, name="org_plan"), default=Plan.FREE, nullable=False)
    is_white_label: Mapped[bool] = mapped_column(default=False, nullable=False)
    white_label_brand_name: Mapped[str | None] = mapped_column(String(200), nullable=True)


class OrganizationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_member"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(OrganizationRole, name="org_member_role"), default=OrganizationRole.MEMBER, nullable=False
    )


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[Plan] = mapped_column(Enum(Plan, name="subscription_plan"), default=Plan.FREE, nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        default=SubscriptionStatus.CONFIGURATION_REQUIRED, nullable=False,
    )
    payment_provider: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    external_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Invoice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "invoices"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="usd", nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # paid | open | void
    external_invoice_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
