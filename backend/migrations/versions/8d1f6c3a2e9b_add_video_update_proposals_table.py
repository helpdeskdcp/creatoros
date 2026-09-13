"""add video update proposals table (verified update engine)

Revision ID: 8d1f6c3a2e9b
Revises: 7c2e4a9f8b1d
Create Date: 2026-09-13 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '8d1f6c3a2e9b'
down_revision: Union[str, None] = '7c2e4a9f8b1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'video_update_proposals',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('video_id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column(
            'field',
            sa.Enum('TITLE', 'DESCRIPTION', 'TAGS', name='video_update_field'),
            nullable=False,
        ),
        sa.Column('previous_value', sa.Text(), nullable=True),
        sa.Column('verified_previous_value', sa.Text(), nullable=True),
        sa.Column('proposed_value', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'PENDING_APPROVAL', 'REJECTED', 'EXECUTING', 'SUCCEEDED_VERIFIED',
                'FAILED_NOT_VERIFIED', name='video_update_status',
            ),
            nullable=False,
        ),
        sa.Column('approved_by_user_id', GUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('rollback_of_id', GUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rollback_of_id'], ['video_update_proposals.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_video_update_proposals_video_id'), 'video_update_proposals', ['video_id'])
    op.create_index(op.f('ix_video_update_proposals_owner_user_id'), 'video_update_proposals', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_video_update_proposals_owner_user_id'), table_name='video_update_proposals')
    op.drop_index(op.f('ix_video_update_proposals_video_id'), table_name='video_update_proposals')
    op.drop_table('video_update_proposals')
    bind = op.get_bind()
    sa.Enum(name='video_update_status').drop(bind, checkfirst=True)
    sa.Enum(name='video_update_field').drop(bind, checkfirst=True)
