"""add prediction records table (probability engine)

Revision ID: 9e4b7d2c1a5f
Revises: 8d1f6c3a2e9b
Create Date: 2026-09-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '9e4b7d2c1a5f'
down_revision: Union[str, None] = '8d1f6c3a2e9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'prediction_records',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column('channel_id', GUID(), nullable=False),
        sa.Column('video_id', GUID(), nullable=True),
        sa.Column('metric', sa.Enum('VIEWS', 'SUBSCRIBERS', name='prediction_metric'), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('horizon_days', sa.Integer(), nullable=False),
        sa.Column('probability_percent', sa.Integer(), nullable=True),
        sa.Column(
            'confidence',
            sa.Enum('LOW', 'MEDIUM', 'HIGH', 'INSUFFICIENT_DATA', name='prediction_confidence'),
            nullable=False,
        ),
        sa.Column('comparable_video_count', sa.Integer(), nullable=False),
        sa.Column('positive_factors', sa.Text(), nullable=True),
        sa.Column('negative_factors', sa.Text(), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('model_version', sa.String(length=32), nullable=False),
        sa.Column('data_freshness_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_value', sa.Integer(), nullable=True),
        sa.Column('actual_outcome', sa.Enum('MET', 'NOT_MET', name='prediction_outcome'), nullable=True),
        sa.Column('outcome_recorded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_prediction_records_owner_user_id'), 'prediction_records', ['owner_user_id'])
    op.create_index(op.f('ix_prediction_records_channel_id'), 'prediction_records', ['channel_id'])
    op.create_index(op.f('ix_prediction_records_video_id'), 'prediction_records', ['video_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_prediction_records_video_id'), table_name='prediction_records')
    op.drop_index(op.f('ix_prediction_records_channel_id'), table_name='prediction_records')
    op.drop_index(op.f('ix_prediction_records_owner_user_id'), table_name='prediction_records')
    op.drop_table('prediction_records')
    bind = op.get_bind()
    sa.Enum(name='prediction_outcome').drop(bind, checkfirst=True)
    sa.Enum(name='prediction_confidence').drop(bind, checkfirst=True)
    sa.Enum(name='prediction_metric').drop(bind, checkfirst=True)
