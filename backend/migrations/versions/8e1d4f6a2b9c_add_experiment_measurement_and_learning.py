"""add experiment variant video_id/measured_at and creator_learning_signals

Revision ID: 8e1d4f6a2b9c
Revises: 6b4f8e2a1c7d
Create Date: 2026-09-13 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '8e1d4f6a2b9c'
down_revision: Union[str, None] = '6b4f8e2a1c7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('experiment_variants', sa.Column('video_id', GUID(), nullable=True))
    op.add_column('experiment_variants', sa.Column('measured_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_experiment_variants_video_id', 'experiment_variants', 'videos',
        ['video_id'], ['id'], ondelete='SET NULL',
    )

    op.create_table(
        'creator_learning_signals',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column('signal_type', sa.String(length=32), nullable=False),
        sa.Column('signal_key', sa.String(length=200), nullable=False),
        sa.Column('wins', sa.Integer(), nullable=False),
        sa.Column('losses', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_user_id', 'signal_type', 'signal_key', name='uq_learning_signal'),
    )
    op.create_index(
        op.f('ix_creator_learning_signals_owner_user_id'), 'creator_learning_signals', ['owner_user_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_creator_learning_signals_owner_user_id'), table_name='creator_learning_signals')
    op.drop_table('creator_learning_signals')
    op.drop_constraint('fk_experiment_variants_video_id', 'experiment_variants', type_='foreignkey')
    op.drop_column('experiment_variants', 'measured_at')
    op.drop_column('experiment_variants', 'video_id')
