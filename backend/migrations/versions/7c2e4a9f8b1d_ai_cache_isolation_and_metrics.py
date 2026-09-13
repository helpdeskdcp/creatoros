"""ai cache creator isolation, ttl, mode; ai request metrics table

Revision ID: 7c2e4a9f8b1d
Revises: 5f2a8c1e9b4d
Create Date: 2026-09-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '7c2e4a9f8b1d'
down_revision: Union[str, None] = '5f2a8c1e9b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_generation_cache', sa.Column('mode', sa.String(length=8), nullable=False, server_default='fast'))
    op.add_column('ai_generation_cache', sa.Column('owner_user_id', GUID(), nullable=True))
    # Nullable during backfill; existing rows get expires_at = created_at
    # (i.e. already expired -- safe: a "miss" on next lookup is functionally
    # identical to a cold cache, never a stale/wrong result served).
    op.add_column('ai_generation_cache', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE ai_generation_cache SET expires_at = created_at WHERE expires_at IS NULL")
    op.alter_column('ai_generation_cache', 'expires_at', nullable=False)
    op.alter_column('ai_generation_cache', 'mode', server_default=None)

    op.create_index(
        op.f('ix_ai_generation_cache_owner_user_id'), 'ai_generation_cache', ['owner_user_id']
    )
    op.create_index(
        op.f('ix_ai_generation_cache_expires_at'), 'ai_generation_cache', ['expires_at']
    )

    op.drop_constraint('uq_ai_cache_key', 'ai_generation_cache', type_='unique')
    op.create_unique_constraint(
        'uq_ai_cache_key', 'ai_generation_cache',
        ['task', 'prompt_version', 'model', 'mode', 'input_hash', 'owner_user_id'],
    )

    op.create_table(
        'ai_request_metrics',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('task', sa.String(length=64), nullable=False),
        sa.Column('mode', sa.String(length=8), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('cache_hit', sa.Boolean(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_code', sa.String(length=32), nullable=True),
        sa.Column('latency_ms', sa.BigInteger(), nullable=False),
        sa.Column('queue_wait_ms', sa.BigInteger(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ai_request_metrics_task'), 'ai_request_metrics', ['task'])
    op.create_index(op.f('ix_ai_request_metrics_created_at'), 'ai_request_metrics', ['created_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_request_metrics_created_at'), table_name='ai_request_metrics')
    op.drop_index(op.f('ix_ai_request_metrics_task'), table_name='ai_request_metrics')
    op.drop_table('ai_request_metrics')

    op.drop_constraint('uq_ai_cache_key', 'ai_generation_cache', type_='unique')
    op.create_unique_constraint(
        'uq_ai_cache_key', 'ai_generation_cache', ['task', 'prompt_version', 'model', 'input_hash']
    )
    op.drop_index(op.f('ix_ai_generation_cache_expires_at'), table_name='ai_generation_cache')
    op.drop_index(op.f('ix_ai_generation_cache_owner_user_id'), table_name='ai_generation_cache')
    op.drop_column('ai_generation_cache', 'expires_at')
    op.drop_column('ai_generation_cache', 'owner_user_id')
    op.drop_column('ai_generation_cache', 'mode')
