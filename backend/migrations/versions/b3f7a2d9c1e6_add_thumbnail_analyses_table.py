"""add thumbnail analyses table (thumbnail vision)

Revision ID: b3f7a2d9c1e6
Revises: a1c8e5f3b7d2
Create Date: 2026-09-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = 'b3f7a2d9c1e6'
down_revision: Union[str, None] = 'a1c8e5f3b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'thumbnail_analyses',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('video_id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column('image_url', sa.String(length=1000), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('meets_min_resolution', sa.Boolean(), nullable=False),
        sa.Column('meets_aspect_ratio', sa.Boolean(), nullable=False),
        sa.Column('contrast_score', sa.Float(), nullable=False),
        sa.Column('brightness_score', sa.Float(), nullable=False),
        sa.Column('colorfulness_score', sa.Float(), nullable=False),
        sa.Column('subject_prominence_score', sa.Float(), nullable=False),
        sa.Column('recommendations_json', sa.Text(), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_thumbnail_analyses_video_id'), 'thumbnail_analyses', ['video_id'])
    op.create_index(op.f('ix_thumbnail_analyses_owner_user_id'), 'thumbnail_analyses', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_thumbnail_analyses_owner_user_id'), table_name='thumbnail_analyses')
    op.drop_index(op.f('ix_thumbnail_analyses_video_id'), table_name='thumbnail_analyses')
    op.drop_table('thumbnail_analyses')
