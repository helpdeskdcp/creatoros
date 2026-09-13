"""add publishing_run scheduling fields

Revision ID: 2f7e1a9c5d3b
Revises: 4d8b2c6e9a1f
Create Date: 2026-09-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '2f7e1a9c5d3b'
down_revision: Union[str, None] = '4d8b2c6e9a1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('publishing_runs', sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('publishing_runs', sa.Column('cancelled_by_user_id', GUID(), nullable=True))
    op.add_column('publishing_runs', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'publishing_runs',
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_foreign_key(
        'fk_publishing_runs_cancelled_by_user_id', 'publishing_runs', 'users',
        ['cancelled_by_user_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_publishing_runs_scheduled_at'), 'publishing_runs', ['scheduled_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_publishing_runs_scheduled_at'), table_name='publishing_runs')
    op.drop_constraint('fk_publishing_runs_cancelled_by_user_id', 'publishing_runs', type_='foreignkey')
    op.drop_column('publishing_runs', 'retry_count')
    op.drop_column('publishing_runs', 'cancelled_at')
    op.drop_column('publishing_runs', 'cancelled_by_user_id')
    op.drop_column('publishing_runs', 'scheduled_at')
