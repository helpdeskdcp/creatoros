"""add billing organizations tables

Revision ID: 5f2a8c1e9b4d
Revises: 3a7c9e5f1d2b
Create Date: 2026-09-13 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '5f2a8c1e9b4d'
down_revision: Union[str, None] = '3a7c9e5f1d2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Each enum is only ever used on a single column below -- op.create_table
    # already emits CREATE TYPE for it (create_type defaults to True), so an
    # extra explicit .create() call here would collide with that and fail.
    org_plan = sa.Enum('FREE', 'PRO', 'AGENCY', 'ENTERPRISE', name='org_plan')
    subscription_plan = sa.Enum('FREE', 'PRO', 'AGENCY', 'ENTERPRISE', name='subscription_plan')
    org_member_role = sa.Enum('OWNER', 'ADMIN', 'MEMBER', name='org_member_role')
    subscription_status = sa.Enum(
        'ACTIVE', 'TRIALING', 'PAST_DUE', 'CANCELED', 'CONFIGURATION_REQUIRED',
        name='subscription_status',
    )

    op.create_table(
        'organizations',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('plan', org_plan, nullable=False),
        sa.Column('is_white_label', sa.Boolean(), nullable=False),
        sa.Column('white_label_brand_name', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'organization_members',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('organization_id', GUID(), nullable=False),
        sa.Column('user_id', GUID(), nullable=False),
        sa.Column('role', org_member_role, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_member'),
    )
    op.create_index(op.f('ix_organization_members_organization_id'), 'organization_members', ['organization_id'])
    op.create_index(op.f('ix_organization_members_user_id'), 'organization_members', ['user_id'])

    op.create_table(
        'subscriptions',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('organization_id', GUID(), nullable=False),
        sa.Column('plan', subscription_plan, nullable=False),
        sa.Column('status', subscription_status, nullable=False),
        sa.Column('payment_provider', sa.String(32), nullable=False),
        sa.Column('external_subscription_id', sa.String(200), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id'),
    )

    op.create_table(
        'invoices',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('organization_id', GUID(), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('external_invoice_id', sa.String(200), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoices_organization_id'), 'invoices', ['organization_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_invoices_organization_id'), table_name='invoices')
    op.drop_table('invoices')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_organization_members_user_id'), table_name='organization_members')
    op.drop_index(op.f('ix_organization_members_organization_id'), table_name='organization_members')
    op.drop_table('organization_members')
    op.drop_table('organizations')

    bind = op.get_bind()
    sa.Enum(name='subscription_status').drop(bind, checkfirst=True)
    sa.Enum(name='org_member_role').drop(bind, checkfirst=True)
    sa.Enum(name='subscription_plan').drop(bind, checkfirst=True)
    sa.Enum(name='org_plan').drop(bind, checkfirst=True)
