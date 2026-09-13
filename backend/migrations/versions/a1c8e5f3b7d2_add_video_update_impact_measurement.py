"""add video update impact measurement fields (learning loop)

Revision ID: a1c8e5f3b7d2
Revises: 9e4b7d2c1a5f
Create Date: 2026-09-13 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c8e5f3b7d2'
down_revision: Union[str, None] = '9e4b7d2c1a5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unlike op.create_table (which auto-creates an Enum's Postgres type
    # inline), op.add_column on an EXISTING table does not -- the type
    # must be created explicitly first (confirmed live: this migration
    # failed with UndefinedObjectError on first attempt without this).
    impact_enum = sa.Enum('WIN', 'NEUTRAL', 'LOSS', 'INCONCLUSIVE', name='video_update_impact')
    impact_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'video_update_proposals',
        sa.Column('observation_window_days', sa.Integer(), nullable=False, server_default='14'),
    )
    op.alter_column('video_update_proposals', 'observation_window_days', server_default=None)
    op.add_column('video_update_proposals', sa.Column('baseline_view_velocity', sa.Float(), nullable=True))
    op.add_column('video_update_proposals', sa.Column('post_view_velocity', sa.Float(), nullable=True))
    op.add_column('video_update_proposals', sa.Column('impact_outcome', impact_enum, nullable=True))
    op.add_column(
        'video_update_proposals', sa.Column('impact_measured_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('video_update_proposals', 'impact_measured_at')
    op.drop_column('video_update_proposals', 'impact_outcome')
    op.drop_column('video_update_proposals', 'post_view_velocity')
    op.drop_column('video_update_proposals', 'baseline_view_velocity')
    op.drop_column('video_update_proposals', 'observation_window_days')
    bind = op.get_bind()
    sa.Enum(name='video_update_impact').drop(bind, checkfirst=True)
