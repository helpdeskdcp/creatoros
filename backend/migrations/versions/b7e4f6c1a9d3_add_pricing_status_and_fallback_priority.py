"""add pricing_status and fallback_priority to video model catalog

Revision ID: b7e4f6c1a9d3
Revises: f1a6c9d2e4b8
Create Date: 2026-09-15 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7e4f6c1a9d3'
down_revision: Union[str, None] = 'f1a6c9d2e4b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_model_catalog',
        sa.Column('pricing_status', sa.String(length=16), nullable=False, server_default='PAID'),
    )
    op.create_index(
        op.f('ix_video_model_catalog_pricing_status'), 'video_model_catalog', ['pricing_status']
    )
    op.add_column(
        'video_model_catalog',
        sa.Column('fallback_priority', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_video_model_catalog_fallback_priority'), 'video_model_catalog', ['fallback_priority']
    )
    # Backfill: every existing row today is an OpenRouter row with
    # confidently-known pricing -- FREE where is_free is already true,
    # PAID otherwise (the column default). No existing row should ever
    # start out UNKNOWN.
    op.execute("UPDATE video_model_catalog SET pricing_status = 'FREE' WHERE is_free = true")


def downgrade() -> None:
    op.drop_index(op.f('ix_video_model_catalog_fallback_priority'), table_name='video_model_catalog')
    op.drop_column('video_model_catalog', 'fallback_priority')
    op.drop_index(op.f('ix_video_model_catalog_pricing_status'), table_name='video_model_catalog')
    op.drop_column('video_model_catalog', 'pricing_status')
