"""add publishing_run execution fields

Revision ID: 9c3e7d1a4f6b
Revises: 7a1f9c4e2b3d
Create Date: 2026-09-13 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9c3e7d1a4f6b'
down_revision: Union[str, None] = '7a1f9c4e2b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('publishing_runs', sa.Column('published_url', sa.String(length=300), nullable=True))
    op.add_column('publishing_runs', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('publishing_runs', 'published_at')
    op.drop_column('publishing_runs', 'published_url')
