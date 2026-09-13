"""add window_view_count to video_metrics

Revision ID: 7a1f9c4e2b3d
Revises: 2bcbcb330485
Create Date: 2026-09-13 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7a1f9c4e2b3d'
down_revision: Union[str, None] = '2bcbcb330485'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('video_metrics', sa.Column('window_view_count', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('video_metrics', 'window_view_count')
