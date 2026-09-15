"""add zdr blocking tracking to video model catalog

Revision ID: d5e8b3f7a1c9
Revises: c4a9f1e2d8b3
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd5e8b3f7a1c9'
down_revision: Union[str, None] = 'c4a9f1e2d8b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_model_catalog',
        sa.Column('known_zdr_blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'video_model_catalog',
        sa.Column('zdr_blocked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_video_model_catalog_known_zdr_blocked'), 'video_model_catalog', ['known_zdr_blocked']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_video_model_catalog_known_zdr_blocked'), table_name='video_model_catalog')
    op.drop_column('video_model_catalog', 'zdr_blocked_at')
    op.drop_column('video_model_catalog', 'known_zdr_blocked')
