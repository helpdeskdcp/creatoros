"""add video generation tables (catalog, jobs, attempts)

Revision ID: c4a9f1e2d8b3
Revises: b3f7a2d9c1e6
Create Date: 2026-09-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = 'c4a9f1e2d8b3'
down_revision: Union[str, None] = 'b3f7a2d9c1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'video_model_catalog',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('model_id', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('supported_resolutions_json', sa.Text(), nullable=True),
        sa.Column('supported_aspect_ratios_json', sa.Text(), nullable=True),
        sa.Column('supported_durations_json', sa.Text(), nullable=True),
        sa.Column('supported_frame_images_json', sa.Text(), nullable=True),
        sa.Column('supports_audio', sa.Boolean(), nullable=False),
        sa.Column('supports_image_reference', sa.Boolean(), nullable=False),
        sa.Column('supports_text_to_video', sa.Boolean(), nullable=False),
        sa.Column('pricing_skus_json', sa.Text(), nullable=True),
        sa.Column('is_free', sa.Boolean(), nullable=False),
        sa.Column('quality_tier_score', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('success_count', sa.Integer(), nullable=False),
        sa.Column('failure_count', sa.Integer(), nullable=False),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('circuit_state', sa.Enum('CLOSED', 'OPEN', 'HALF_OPEN', name='video_model_circuit_state'), nullable=False),
        sa.Column('circuit_opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recent_latencies_ms_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_video_model_catalog_model_id'), 'video_model_catalog', ['model_id'], unique=True)
    op.create_index(op.f('ix_video_model_catalog_provider'), 'video_model_catalog', ['provider'])
    op.create_index(op.f('ix_video_model_catalog_is_free'), 'video_model_catalog', ['is_free'])
    op.create_index(op.f('ix_video_model_catalog_is_active'), 'video_model_catalog', ['is_active'])

    op.create_table(
        'video_jobs',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('owner_user_id', GUID(), nullable=False),
        sa.Column('generation_type', sa.Enum(
            'TEXT_TO_VIDEO', 'IMAGE_TO_VIDEO', 'REFERENCE_TO_VIDEO', 'FIRST_FRAME', 'LAST_FRAME', 'FIRST_LAST_FRAME',
            name='video_generation_type'), nullable=False),
        sa.Column('priority_mode', sa.Enum(
            'QUALITY', 'BALANCED', 'FAST', 'LOW_COST', 'FREE_FIRST', 'AUTO', name='video_priority_mode'
        ), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('requested_params_json', sa.Text(), nullable=False),
        sa.Column('validated_params_json', sa.Text(), nullable=True),
        sa.Column('input_references_json', sa.Text(), nullable=True),
        sa.Column('degraded_from_request', sa.Boolean(), nullable=False),
        sa.Column('degradation_notes_json', sa.Text(), nullable=True),
        sa.Column('primary_model_id', sa.String(length=128), nullable=True),
        sa.Column('fallback_chain_json', sa.Text(), nullable=True),
        sa.Column('selected_model_id', sa.String(length=128), nullable=True),
        sa.Column('provider_job_id', sa.String(length=128), nullable=True),
        sa.Column('status', sa.Enum(
            'QUEUED', 'SUBMITTED', 'PROCESSING', 'COMPLETED', 'FAILED', 'RETRYING', 'CANCELLED', 'EXPIRED',
            name='ai_video_job_status'), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fallback_used', sa.Boolean(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('output_url', sa.String(length=1000), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=1000), nullable=True),
        sa.Column('resolution', sa.String(length=16), nullable=True),
        sa.Column('aspect_ratio', sa.String(length=16), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('cost_estimate', sa.Float(), nullable=True),
        sa.Column('cost_actual', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_video_jobs_owner_user_id'), 'video_jobs', ['owner_user_id'])
    op.create_index(op.f('ix_video_jobs_status'), 'video_jobs', ['status'])
    op.create_index(op.f('ix_video_jobs_provider_job_id'), 'video_jobs', ['provider_job_id'])

    op.create_table(
        'video_generation_attempts',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('video_job_id', GUID(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.String(length=128), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('provider_job_id', sa.String(length=128), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['video_job_id'], ['video_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_video_generation_attempts_video_job_id'), 'video_generation_attempts', ['video_job_id'])
    op.create_index(op.f('ix_video_generation_attempts_model_id'), 'video_generation_attempts', ['model_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_video_generation_attempts_model_id'), table_name='video_generation_attempts')
    op.drop_index(op.f('ix_video_generation_attempts_video_job_id'), table_name='video_generation_attempts')
    op.drop_table('video_generation_attempts')

    op.drop_index(op.f('ix_video_jobs_provider_job_id'), table_name='video_jobs')
    op.drop_index(op.f('ix_video_jobs_status'), table_name='video_jobs')
    op.drop_index(op.f('ix_video_jobs_owner_user_id'), table_name='video_jobs')
    op.drop_table('video_jobs')

    op.drop_index(op.f('ix_video_model_catalog_is_active'), table_name='video_model_catalog')
    op.drop_index(op.f('ix_video_model_catalog_is_free'), table_name='video_model_catalog')
    op.drop_index(op.f('ix_video_model_catalog_provider'), table_name='video_model_catalog')
    op.drop_index(op.f('ix_video_model_catalog_model_id'), table_name='video_model_catalog')
    op.drop_table('video_model_catalog')

    sa.Enum(name='ai_video_job_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='video_generation_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='video_priority_mode').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='video_model_circuit_state').drop(op.get_bind(), checkfirst=True)
