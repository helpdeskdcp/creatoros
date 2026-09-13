"""add competitor_snapshots table

Revision ID: 3a7c9e5f1d2b
Revises: 8e1d4f6a2b9c
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '3a7c9e5f1d2b'
down_revision: Union[str, None] = '8e1d4f6a2b9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'competitor_snapshots',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('competitor_id', GUID(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('subscriber_count', sa.BigInteger(), nullable=True),
        sa.Column('view_count', sa.BigInteger(), nullable=True),
        sa.Column('video_count', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['competitor_id'], ['competitors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_competitor_snapshots_competitor_id'), 'competitor_snapshots', ['competitor_id'])
    op.create_index(op.f('ix_competitor_snapshots_captured_at'), 'competitor_snapshots', ['captured_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_competitor_snapshots_captured_at'), table_name='competitor_snapshots')
    op.drop_index(op.f('ix_competitor_snapshots_competitor_id'), table_name='competitor_snapshots')
    op.drop_table('competitor_snapshots')
