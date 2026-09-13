"""add media_assets table and publishing_runs.video_media_asset_id

Revision ID: 4d8b2c6e9a1f
Revises: 9c3e7d1a4f6b
Create Date: 2026-09-13 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '4d8b2c6e9a1f'
down_revision: Union[str, None] = '9c3e7d1a4f6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'media_assets',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column('purpose', sa.Enum('VIDEO', 'THUMBNAIL', name='media_purpose'), nullable=False),
        sa.Column('storage_backend', sa.String(length=16), nullable=False),
        sa.Column('storage_key', sa.String(length=500), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_media_assets_owner_user_id'), 'media_assets', ['owner_user_id'], unique=False)
    op.add_column('publishing_runs', sa.Column('video_media_asset_id', GUID(), nullable=True))
    op.create_foreign_key(
        'fk_publishing_runs_video_media_asset_id', 'publishing_runs', 'media_assets',
        ['video_media_asset_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_publishing_runs_video_media_asset_id', 'publishing_runs', type_='foreignkey')
    op.drop_column('publishing_runs', 'video_media_asset_id')
    op.drop_index(op.f('ix_media_assets_owner_user_id'), table_name='media_assets')
    op.drop_table('media_assets')
    sa.Enum(name='media_purpose').drop(op.get_bind(), checkfirst=True)
