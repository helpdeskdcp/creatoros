"""End-to-end content-factory pipeline tests. Audio extraction and
vertical-clip rendering run against REAL ffmpeg on a real (ffmpeg-
synthesized) test video -- no mocking of the media pipeline itself.
Transcription and AI-metadata-generation use deterministic fake
providers (monkeypatched at their call sites), matching how the rest of
the codebase already tests AI/ML dependencies (see test_audit_coverage's
_ScriptedHookProvider) -- running a real Whisper model or hitting a real
LLM in the automated suite would be slow and non-deterministic, not more
correct."""
import asyncio
import io
import json
import uuid

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.modules.media.models import MediaPurpose
from app.modules.shorts import service as shorts_service
from app.modules.shorts.models import ShortCandidateStatus, VideoJobStatus
from app.modules.shorts.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptSegmentResult,
)


class _FakeTranscriptionProvider(TranscriptionProvider):
    name = "fake-test-provider"

    async def transcribe(self, audio_file_path: str) -> TranscriptionResult:
        segments = [
            TranscriptSegmentResult(0.0, 6.0, "Here's the secret nobody tells you about growing fast."),
            TranscriptSegmentResult(6.0, 12.0, "Most creators quit after just ten videos and never see results."),
            TranscriptSegmentResult(12.0, 20.0, "So um yeah I was just kind of thinking about stuff you know."),
        ]
        return TranscriptionResult(
            full_text=" ".join(s.text for s in segments), language="en", segments=segments,
            provider=self.name,
        )


async def _make_test_video(path: str, duration: int = 20, width: int = 640, height: int = 360) -> None:
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()


@pytest.fixture(scope="module")
def shared_test_video_bytes(tmp_path_factory):
    """Synthesizing a 20s test video with ffmpeg takes a few real seconds
    -- doing it once for the whole module instead of once per test keeps
    this suite from spending most of its wall-clock time on fixture
    setup rather than the pipeline logic it's actually testing."""
    video_dir = tmp_path_factory.mktemp("shared_video")
    video_path = str(video_dir / "source.mp4")
    asyncio.run(_make_test_video(video_path))
    with open(video_path, "rb") as f:
        return f.read()


async def _register(client) -> tuple[str, str]:
    email = f"shorts-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _upload_test_video(client, token: str, video_bytes: bytes) -> str:
    resp = await client.post(
        "/api/v1/media/upload",
        data={"purpose": "VIDEO"},
        files={"file": ("source.mp4", io.BytesIO(video_bytes), "video/mp4")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class _FakeShortMetadata:
    def __init__(self, title, hook, description):
        self.title = title
        self.hook = hook
        self.description = description


async def _fake_generate_short_metadata(db, orchestrator, owner_user_id, transcript_excerpt):
    return _FakeShortMetadata(
        title="Fake generated title", hook="Fake hook", description="Fake description",
    )


@pytest.fixture(autouse=True)
def _fake_ai_and_transcription(monkeypatch):
    monkeypatch.setattr(shorts_service, "get_transcription_provider", lambda: _FakeTranscriptionProvider())
    monkeypatch.setattr(shorts_service, "generate_short_metadata", _fake_generate_short_metadata)
    yield


@pytest.mark.asyncio
async def test_process_job_runs_full_pipeline_to_ready_for_review(client, db_session, shared_test_video_bytes):
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)

    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-1")
    assert job.status == VideoJobStatus.QUEUED

    job = await shorts_service.process_job(db_session, job)

    assert job.status == VideoJobStatus.READY_FOR_REVIEW
    assert job.progress_pct == 100
    assert job.source_duration_seconds is not None
    assert 18 < job.source_duration_seconds < 22

    candidates = await shorts_service.list_candidates(db_session, job.id)
    assert len(candidates) > 0
    for c in candidates:
        assert c.status == ShortCandidateStatus.PENDING_APPROVAL
        assert c.generated_title == "Fake generated title"
        breakdown = json.loads(c.score_breakdown_json)
        assert "weighted_total" in breakdown
        # Non-overlapping, per moment_detection's own contract.
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            assert not (a.start_seconds < b.end_seconds and b.start_seconds < a.end_seconds)


@pytest.mark.asyncio
async def test_process_job_ranks_the_hook_moment_above_the_filler_moment(client, db_session, shared_test_video_bytes):
    """Proves moment detection is actually wired end-to-end, not just
    unit-tested in isolation: the real hook-containing segment should
    outrank the real filler segment once run through the full job."""
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)
    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-rank")

    job = await shorts_service.process_job(db_session, job)
    candidates = await shorts_service.list_candidates(db_session, job.id)

    top = candidates[0]
    assert "secret" in top.transcript_excerpt.lower() or "quit" in top.transcript_excerpt.lower()


@pytest.mark.asyncio
async def test_process_job_is_idempotent_on_retry(client, db_session, shared_test_video_bytes):
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)
    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-retry")

    job = await shorts_service.process_job(db_session, job)
    first_candidates = await shorts_service.list_candidates(db_session, job.id)

    # Simulate a retried Celery dispatch of an already-finished job.
    job = await shorts_service.process_job(db_session, job)
    second_candidates = await shorts_service.list_candidates(db_session, job.id)

    assert len(first_candidates) == len(second_candidates)
    assert {c.id for c in first_candidates} == {c.id for c in second_candidates}  # no duplicates created


@pytest.mark.asyncio
async def test_create_job_refuses_another_users_media_asset(client, db_session, shared_test_video_bytes):
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)

    other_token, other_user_id = await _register(client)

    with pytest.raises(NotFoundError):
        await shorts_service.create_job(
            db_session, uuid.UUID(other_user_id), uuid.UUID(asset_id), "job-adversarial"
        )


@pytest.mark.asyncio
async def test_approve_and_render_candidate_produces_a_real_vertical_clip(client, db_session, shared_test_video_bytes):
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)
    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-render")
    job = await shorts_service.process_job(db_session, job)
    candidates = await shorts_service.list_candidates(db_session, job.id)
    candidate = candidates[0]

    candidate = await shorts_service.approve_candidate(db_session, candidate, uuid.UUID(user_id))
    assert candidate.status == ShortCandidateStatus.APPROVED

    candidate = await shorts_service.render_candidate(db_session, candidate)

    assert candidate.status == ShortCandidateStatus.RENDERED
    assert candidate.rendered_media_asset_id is not None
    assert candidate.rendered_at is not None

    from app.modules.media.models import MediaAsset
    from app.modules.media.service import local_path_for

    rendered_asset = await db_session.get(MediaAsset, candidate.rendered_media_asset_id)
    assert rendered_asset.owner_user_id == uuid.UUID(user_id)
    assert rendered_asset.purpose == MediaPurpose.VIDEO

    from app.core.ffmpeg import probe

    rendered_path = local_path_for(rendered_asset)
    result = await probe(rendered_path)
    assert result.width == 1080
    assert result.height == 1920


@pytest.mark.asyncio
async def test_render_candidate_refuses_a_candidate_not_yet_approved(client, db_session, shared_test_video_bytes):
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)
    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-noapprove")
    job = await shorts_service.process_job(db_session, job)
    candidate = (await shorts_service.list_candidates(db_session, job.id))[0]

    with pytest.raises(ConflictError):
        await shorts_service.render_candidate(db_session, candidate)


@pytest.mark.asyncio
async def test_reject_candidate_marks_it_rejected(client, db_session, shared_test_video_bytes):
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)
    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-reject")
    job = await shorts_service.process_job(db_session, job)
    candidate = (await shorts_service.list_candidates(db_session, job.id))[0]

    candidate = await shorts_service.reject_candidate(db_session, candidate, uuid.UUID(user_id))

    assert candidate.status == ShortCandidateStatus.REJECTED
    with pytest.raises(ConflictError):
        await shorts_service.approve_candidate(db_session, candidate, uuid.UUID(user_id))


@pytest.mark.asyncio
async def test_candidate_endpoints_refuse_another_users_job(client, db_session, shared_test_video_bytes):
    """Adversarial: ShortCandidate has no owner column of its own --
    ownership must flow correctly through its parent job via the
    join-based check in router._get_owned_candidate."""
    token, user_id = await _register(client)
    asset_id = await _upload_test_video(client, token, shared_test_video_bytes)
    job = await shorts_service.create_job(db_session, uuid.UUID(user_id), uuid.UUID(asset_id), "job-adv2")
    job = await shorts_service.process_job(db_session, job)
    candidate = (await shorts_service.list_candidates(db_session, job.id))[0]

    # Deliberately elevated to OWNER (not the default VIEWER a second
    # registration gets) so this actually exercises the ownership check
    # in _get_owned_candidate rather than being turned away earlier by
    # require_editor's role gate -- a real attacker with their own
    # legitimate editor-level account is the threat model here.
    from app.core.security import create_jwt
    from app.modules.users.models import User, UserRole

    attacker = User(email="shorts-attacker@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(attacker)
    await db_session.commit()
    attacker_token, _ = create_jwt(subject=str(attacker.id), token_type="access")
    headers = {"Authorization": f"Bearer {attacker_token}"}

    approve_resp = await client.post(f"/api/v1/shorts/candidates/{candidate.id}/approve", headers=headers)
    reject_resp = await client.post(f"/api/v1/shorts/candidates/{candidate.id}/reject", headers=headers)
    job_resp = await client.get(f"/api/v1/shorts/jobs/{job.id}", headers=headers)

    assert approve_resp.status_code == 404
    assert reject_resp.status_code == 404
    assert job_resp.status_code == 404

    await db_session.refresh(candidate)
    assert candidate.status == ShortCandidateStatus.PENDING_APPROVAL  # untouched
