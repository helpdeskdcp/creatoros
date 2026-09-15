"""add free-first billing visibility fields to video jobs

Revision ID: f1a6c9d2e4b8
Revises: d5e8b3f7a1c9
Create Date: 2026-09-15 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f1a6c9d2e4b8'
down_revision: Union[str, None] = 'd5e8b3f7a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_jobs',
        sa.Column('is_free_route', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'video_jobs',
        sa.Column('paid_fallback_used', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('video_jobs', 'paid_fallback_used')
    op.drop_column('video_jobs', 'is_free_route')
