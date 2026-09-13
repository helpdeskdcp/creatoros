"""add shorts content factory tables

Revision ID: 6b4f8e2a1c7d
Revises: 2f7e1a9c5d3b
Create Date: 2026-09-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = '6b4f8e2a1c7d'
down_revision: Union[str, None] = '2f7e1a9c5d3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'video_processing_jobs',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column('source_media_asset_id', GUID(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'QUEUED', 'VALIDATING', 'EXTRACTING_AUDIO', 'TRANSCRIBING', 'DETECTING_MOMENTS',
                'READY_FOR_REVIEW', 'RENDERING', 'COMPLETED', 'FAILED', name='video_job_status',
            ),
            nullable=False,
        ),
        sa.Column('progress_pct', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('source_duration_seconds', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_media_asset_id'], ['media_assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index(op.f('ix_video_processing_jobs_owner_user_id'), 'video_processing_jobs', ['owner_user_id'])
    op.create_index(op.f('ix_video_processing_jobs_status'), 'video_processing_jobs', ['status'])

    op.create_table(
        'transcripts',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('job_id', GUID(), nullable=False),
        sa.Column('full_text', sa.Text(), nullable=False),
        sa.Column('language', sa.String(length=16), nullable=True),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['video_processing_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id'),
    )

    op.create_table(
        'transcript_segments',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('transcript_id', GUID(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('start_seconds', sa.Float(), nullable=False),
        sa.Column('end_seconds', sa.Float(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['transcript_id'], ['transcripts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transcript_segments_transcript_id'), 'transcript_segments', ['transcript_id'])

    op.create_table(
        'short_candidates',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('job_id', GUID(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('start_seconds', sa.Float(), nullable=False),
        sa.Column('end_seconds', sa.Float(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('score_breakdown_json', sa.Text(), nullable=False),
        sa.Column('transcript_excerpt', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'RENDERING', 'RENDERED', 'RENDER_FAILED',
                name='short_candidate_status',
            ),
            nullable=False,
        ),
        sa.Column('generated_title', sa.String(length=200), nullable=True),
        sa.Column('generated_description', sa.Text(), nullable=True),
        sa.Column('generated_hook', sa.Text(), nullable=True),
        sa.Column('rendered_media_asset_id', GUID(), nullable=True),
        sa.Column('render_error', sa.Text(), nullable=True),
        sa.Column('rendered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['video_processing_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rendered_media_asset_id'], ['media_assets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_short_candidates_job_id'), 'short_candidates', ['job_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_short_candidates_job_id'), table_name='short_candidates')
    op.drop_table('short_candidates')
    op.drop_index(op.f('ix_transcript_segments_transcript_id'), table_name='transcript_segments')
    op.drop_table('transcript_segments')
    op.drop_table('transcripts')
    op.drop_index(op.f('ix_video_processing_jobs_status'), table_name='video_processing_jobs')
    op.drop_index(op.f('ix_video_processing_jobs_owner_user_id'), table_name='video_processing_jobs')
    op.drop_table('video_processing_jobs')
    sa.Enum(name='short_candidate_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='video_job_status').drop(op.get_bind(), checkfirst=True)
