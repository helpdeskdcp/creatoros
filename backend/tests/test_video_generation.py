"""AI Video Generation: catalog discovery/parsing, VideoModelRouter
(capability gating, scoring, fallback chains, closest-valid-config
resolution), the OpenRouter video provider (submit/poll/download,
timeout/rate-limit/security), the job pipeline (submission, escalation,
polling, QC, completion), and circuit breaker / new-model-discovery
behavior.

Per this codebase's established convention: production code talks to the
real OpenRouter video API (see the live-verification report); tests fake
the transport layer so CI never makes a real network call or spends real
money on video generation.
"""
import json
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.ai.providers.base import (
    AIGenerationTimeoutError,
    AIProviderError,
    AIProviderUnavailableError,
    ModelNotAvailableError,
    PrivacyPolicyViolationError,
    RateLimitedError,
)
from app.core.config import get_settings
from app.core.errors import ValidationError
from app.modules.users.models import User, UserRole
from app.modules.video_generation import service as vg_service
from app.modules.video_generation.models import (
    AIVideoJobStatus,
    VideoGenerationAttempt,
    VideoGenerationType,
    VideoPriorityMode,
)
from app.video import catalog as catalog_module
from app.video.models import CircuitState, VideoModelCatalogEntry
from app.video.providers.openrouter_video import OpenRouterVideoProvider, VideoGenerationJobResult
from app.video.qc import run_qc
from app.video.router import (
    NoCompatibleModelError,
    VideoRequest,
    passes_hard_gate,
    select_best_model,
)

FAKE_KEY = "sk-or-v1-test-video-key-should-never-appear-in-any-log"


def _model(
    model_id="acme/fast-model",
    *,
    resolutions=None, aspect_ratios=None, durations=None, frame_images=None,
    audio=False, is_free=False, is_active=True, circuit_state=CircuitState.CLOSED,
    quality=0.6, pricing=None,
) -> VideoModelCatalogEntry:
    return VideoModelCatalogEntry(
        model_id=model_id, name=model_id, provider=model_id.split("/")[0],
        description="A video generation model for text-to-video and image-to-video.",
        supported_resolutions_json=json.dumps(resolutions) if resolutions is not None else None,
        supported_aspect_ratios_json=json.dumps(aspect_ratios) if aspect_ratios is not None else None,
        supported_durations_json=json.dumps(durations) if durations is not None else None,
        supported_frame_images_json=json.dumps(frame_images) if frame_images is not None else None,
        supports_audio=audio, supports_image_reference=True, supports_text_to_video=True,
        pricing_skus_json=json.dumps(pricing or {}), is_free=is_free,
        quality_tier_score=quality, is_active=is_active, circuit_state=circuit_state,
        last_checked_at=datetime.now(UTC),
        # SQLAlchemy column defaults (default=0) only apply once a row is
        # actually flushed to a session -- these tests construct plain
        # Python objects, so set them explicitly to mirror a real
        # persisted row's post-flush state.
        success_count=0, failure_count=0, consecutive_failures=0,
    )


# ---------------------------------------------------------------------------
# 1/2/3. Model discovery, capability parsing, free-model detection
# ---------------------------------------------------------------------------

def test_normalize_model_parses_real_openrouter_shape():
    raw = {
        "id": "google/veo-3.1", "name": "Google: Veo 3.1",
        "supported_resolutions": ["720p", "1080p", "4K"],
        "supported_aspect_ratios": ["16:9", "9:16"],
        "supported_durations": [4, 6, 8],
        "supported_frame_images": ["first_frame", "last_frame"],
        "generate_audio": True,
        "pricing_skus": {"duration_seconds_with_audio": "0.40"},
        "description": "Google's video generation model",
    }
    normalized = catalog_module.normalize_model(raw)
    assert normalized["model_id"] == "google/veo-3.1"
    assert normalized["provider"] == "google"
    assert normalized["supports_audio"] is True
    assert json.loads(normalized["supported_frame_images_json"]) == ["first_frame", "last_frame"]
    assert normalized["is_free"] is False


def test_free_model_detection_requires_all_pricing_zero():
    assert catalog_module._is_free({"duration_seconds": "0"}) is True
    assert catalog_module._is_free({"duration_seconds": "0.05"}) is False
    assert catalog_module._is_free({}) is False


def test_image_only_model_inferred_as_not_text_to_video():
    normalized = catalog_module.normalize_model({
        "id": "heygen/avatar-iv",
        "description": "HeyGen: Avatar IV is an image-to-video model that animates a single photo.",
    })
    assert normalized["supports_text_to_video"] is False


def test_unknown_model_gets_default_quality_score_not_a_crash():
    normalized = catalog_module.normalize_model({"id": "brand-new/never-seen-model"})
    assert normalized["quality_tier_score"] == catalog_module._DEFAULT_QUALITY_SCORE


class _FakeAsyncClient:
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text="", headers=None):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json_body


@pytest.mark.asyncio
async def test_refresh_catalog_adds_new_and_deactivates_missing_models(db_session, monkeypatch):
    settings = get_settings()
    settings.openrouter_api_key = FAKE_KEY
    monkeypatch.setattr(
        "app.video.catalog.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"data": [
            {"id": "model/a", "name": "A", "generate_audio": False},
            {"id": "model/b", "name": "B", "generate_audio": True},
        ]})),
    )
    summary = await catalog_module.refresh_catalog(db_session, settings)
    assert summary["added"] == 2

    # Second refresh: "model/b" disappeared, "model/c" is new -- must
    # deactivate b (never delete it) and add c, without touching a.
    monkeypatch.setattr(
        "app.video.catalog.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"data": [
            {"id": "model/a", "name": "A", "generate_audio": False},
            {"id": "model/c", "name": "C", "generate_audio": False},
        ]})),
    )
    summary2 = await catalog_module.refresh_catalog(db_session, settings)
    assert summary2["added"] == 1
    assert summary2["deactivated"] == 1

    from sqlalchemy import select
    row_b = await db_session.scalar(select(VideoModelCatalogEntry).where(VideoModelCatalogEntry.model_id == "model/b"))
    assert row_b is not None  # never deleted
    assert row_b.is_active is False


# ---------------------------------------------------------------------------
# 4-12. Capability validation (hard gate)
# ---------------------------------------------------------------------------

def test_text_to_video_gated_by_supports_text_to_video():
    capable = _model()
    capable.supports_text_to_video = False
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO)
    assert passes_hard_gate(capable, req) is False


def test_image_to_video_supported_by_every_model_per_openrouter_docs():
    model = _model()
    req = VideoRequest(generation_type=VideoGenerationType.IMAGE_TO_VIDEO)
    assert passes_hard_gate(model, req) is True


def test_reference_to_video_supported_by_every_model():
    model = _model()
    req = VideoRequest(generation_type=VideoGenerationType.REFERENCE_TO_VIDEO)
    assert passes_hard_gate(model, req) is True


def test_first_frame_requires_first_frame_capability():
    with_frame = _model(frame_images=["first_frame"])
    without_frame = _model(frame_images=[])
    req = VideoRequest(generation_type=VideoGenerationType.FIRST_FRAME)
    assert passes_hard_gate(with_frame, req) is True
    assert passes_hard_gate(without_frame, req) is False


def test_last_frame_requires_last_frame_capability():
    model = _model(frame_images=["first_frame"])  # has first, not last
    req = VideoRequest(generation_type=VideoGenerationType.LAST_FRAME)
    assert passes_hard_gate(model, req) is False


def test_first_last_frame_requires_both():
    both = _model(frame_images=["first_frame", "last_frame"])
    only_first = _model(frame_images=["first_frame"])
    req = VideoRequest(generation_type=VideoGenerationType.FIRST_LAST_FRAME)
    assert passes_hard_gate(both, req) is True
    assert passes_hard_gate(only_first, req) is False


def test_audio_gate_rejects_model_without_audio_support():
    no_audio = _model(audio=False)
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, audio=True)
    assert passes_hard_gate(no_audio, req) is False


def test_duration_gate_rejects_unsupported_duration():
    model = _model(durations=[4, 8, 12])
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, duration=10)
    assert passes_hard_gate(model, req) is False
    req_ok = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, duration=8)
    assert passes_hard_gate(model, req_ok) is True


def test_resolution_gate_rejects_unsupported_resolution():
    model = _model(resolutions=["720p", "1080p"])
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, resolution="4K")
    assert passes_hard_gate(model, req) is False


def test_aspect_ratio_gate_rejects_unsupported_ratio():
    model = _model(aspect_ratios=["16:9"])
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, aspect_ratio="9:16")
    assert passes_hard_gate(model, req) is False


def test_gate_never_assumes_capability_when_model_field_is_null():
    # OpenRouter returned `supported_resolutions: null` for some models --
    # must never be treated as "supports nothing" or crash.
    model = _model(resolutions=None)
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, resolution="4K")
    assert passes_hard_gate(model, req) is True  # no declared constraint -- not gated out


def test_loads_normalizes_json_null_to_empty_list():
    # json.dumps(None) produces the STRING "null" (truthy, not falsy) --
    # json.loads("null") correctly parses that back to Python None, which
    # must still normalize to [] here. This exact path is what
    # normalize_model() produces for a real OpenRouter model whose
    # supported_resolutions field is a genuine JSON null (e.g.
    # black-forest-labs/flux-video-edit) -- live-verified to crash
    # _resolution_match_score with "argument of type 'NoneType' is not
    # iterable" before this fix.
    from app.video.router import _loads
    assert _loads(json.dumps(None)) == []
    assert _loads(None) == []
    assert _loads("") == []


def test_scoring_never_crashes_on_real_model_with_null_capability_fields():
    # Reproduces the exact production incident via the real normalize_model
    # -> DB column -> score_model path, not a hand-built fixture.
    normalized = catalog_module.normalize_model({
        "id": "black-forest-labs/flux-video-edit",
        "name": "FLUX Video Edit",
        "description": "Video editing model, no declared resolution/duration/aspect-ratio constraints.",
    })
    model = VideoModelCatalogEntry(
        **normalized, is_active=True, circuit_state=CircuitState.CLOSED,
        last_checked_at=datetime.now(UTC), success_count=0, failure_count=0, consecutive_failures=0,
    )
    # normalize_model infers "video editing model" as image-only text_to_video=False,
    # so this specific model is correctly gated out -- the point of this test is
    # that scoring an IMAGE_TO_VIDEO request against it never raises.
    req_image = VideoRequest(generation_type=VideoGenerationType.IMAGE_TO_VIDEO, resolution="480p", duration=2)
    assert passes_hard_gate(model, req_image) is True
    from app.video.router import score_model
    score_model(model, req_image, [model])  # must not raise


# ---------------------------------------------------------------------------
# 13/14. Primary model selection + fallback chain
# ---------------------------------------------------------------------------

def test_select_best_model_picks_highest_scoring_and_orders_fallback():
    high_quality = _model("acme/high", quality=1.0, resolutions=["1080p"])
    mid_quality = _model("acme/mid", quality=0.6, resolutions=["1080p"])
    low_quality = _model("acme/low", quality=0.2, resolutions=["1080p"])
    req = VideoRequest(
        generation_type=VideoGenerationType.TEXT_TO_VIDEO, resolution="1080p",
        priority_mode=VideoPriorityMode.QUALITY,
    )

    selection = select_best_model([low_quality, high_quality, mid_quality], req)
    assert selection.primary_model_id == "acme/high"
    assert selection.fallback_chain == ["acme/mid", "acme/low"]
    assert selection.degraded_from_request is False


def test_free_first_mode_prefers_free_models_when_capable():
    free_model = _model("acme/free", is_free=True, quality=0.4)
    paid_model = _model("acme/paid", is_free=False, quality=1.0)
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, priority_mode=VideoPriorityMode.FREE_FIRST)

    selection = select_best_model([paid_model, free_model], req)
    assert selection.primary_model_id == "acme/free"


def test_free_first_mode_falls_back_to_paid_when_no_free_model_capable():
    paid_only = _model("acme/paid", is_free=False, frame_images=["first_frame"])
    req = VideoRequest(generation_type=VideoGenerationType.FIRST_FRAME, priority_mode=VideoPriorityMode.FREE_FIRST)
    selection = select_best_model([paid_only], req)
    assert selection.primary_model_id == "acme/paid"


def test_no_compatible_model_raises_when_catalog_empty():
    with pytest.raises(NoCompatibleModelError):
        select_best_model([], VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO))


def test_no_compatible_model_error_names_zdr_when_thats_the_actual_reason():
    # Live-observed real scenario: every capability-matching model has
    # already been discovered as ZDR-blocked -- the error must say so
    # specifically, not just "nothing available".
    blocked_a = _model("acme/a", resolutions=["720p"])
    blocked_a.known_zdr_blocked = True
    blocked_b = _model("acme/b", resolutions=["720p"])
    blocked_b.known_zdr_blocked = True
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, resolution="720p")
    with pytest.raises(NoCompatibleModelError, match="privacy policy"):
        select_best_model([blocked_a, blocked_b], req)


def test_no_compatible_model_error_stays_generic_for_genuine_capability_gap():
    # No model anywhere supports first-frame control -- not a ZDR
    # situation (nothing is known_zdr_blocked here), and no
    # duration/resolution/audio downgrade could ever add that capability,
    # so this must fall through to the generic message, never falsely
    # claiming a privacy-policy cause.
    model = _model("acme/a", frame_images=[])
    req = VideoRequest(generation_type=VideoGenerationType.FIRST_FRAME)
    with pytest.raises(NoCompatibleModelError) as exc_info:
        select_best_model([model], req)
    assert "privacy policy" not in str(exc_info.value)


def test_closest_valid_config_degrades_resolution_when_unavailable():
    model_720p = _model("acme/720", resolutions=["720p"])
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, resolution="4K")
    selection = select_best_model([model_720p], req)
    assert selection.degraded_from_request is True
    assert selection.validated_params["resolution"] == "720p"
    assert any("720p" in n for n in selection.notes)


def test_closest_valid_config_disables_audio_when_unavailable():
    no_audio_model = _model("acme/silent", audio=False)
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO, audio=True)
    selection = select_best_model([no_audio_model], req)
    assert selection.degraded_from_request is True
    assert selection.validated_params["audio"] is False


def test_degraded_config_disabled_raises_instead_of_silently_downgrading():
    model_720p = _model("acme/720", resolutions=["720p"])
    req = VideoRequest(
        generation_type=VideoGenerationType.TEXT_TO_VIDEO, resolution="4K", allow_degraded_config=False
    )
    with pytest.raises(NoCompatibleModelError):
        select_best_model([model_720p], req)


def test_open_circuit_model_excluded_from_selection():
    open_model = _model("acme/broken", circuit_state=CircuitState.OPEN)
    closed_model = _model("acme/ok", circuit_state=CircuitState.CLOSED)
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO)
    selection = select_best_model([open_model, closed_model], req)
    assert selection.primary_model_id == "acme/ok"
    assert "acme/broken" not in selection.fallback_chain


# ---------------------------------------------------------------------------
# 18. Circuit breaker
# ---------------------------------------------------------------------------

def test_circuit_opens_after_consecutive_failure_threshold():
    model = _model()
    for _ in range(4):
        catalog_module.record_failure(model, failure_threshold=5)
        assert model.circuit_state == CircuitState.CLOSED
    catalog_module.record_failure(model, failure_threshold=5)
    assert model.circuit_state == CircuitState.OPEN
    assert model.circuit_opened_at is not None


def test_success_resets_consecutive_failures_and_closes_half_open():
    model = _model()
    model.circuit_state = CircuitState.HALF_OPEN
    model.consecutive_failures = 3
    catalog_module.record_success(model, latency_ms=1200)
    assert model.circuit_state == CircuitState.CLOSED
    assert model.consecutive_failures == 0


def test_p95_latency_computed_from_recent_latencies():
    from app.video.router import p95_latency_ms
    model = _model()
    model.recent_latencies_ms_json = json.dumps([1000, 2000, 3000, 4000, 100000])
    p95 = p95_latency_ms(model)
    assert p95 == 100000  # 5 samples -> index round(0.95*4)=4 -> max value


# ---------------------------------------------------------------------------
# OpenRouter video provider: timeout, rate-limit, security, submit/poll
# ---------------------------------------------------------------------------

class _FakeVideoAsyncClient:
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response

    async def get(self, url, headers=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


def _settings_with_key():
    settings = get_settings()
    settings.openrouter_api_key = FAKE_KEY
    return settings


@pytest.mark.asyncio
async def test_submit_job_success_returns_provider_job_id(monkeypatch):
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(_FakeResponse(202, {
            "id": "job-abc123", "status": "pending", "polling_url": "/api/v1/videos/job-abc123",
        })),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    result = await provider.submit_job({"model": "google/veo-3.1", "prompt": "test"})
    assert result.provider_job_id == "job-abc123"
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_submit_job_timeout_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(raise_exc=httpx.ReadTimeout("timed out")),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    with pytest.raises(AIGenerationTimeoutError):
        await provider.submit_job({"model": "x"})


@pytest.mark.asyncio
async def test_submit_job_rate_limited_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(_FakeResponse(429, text="rate limited")),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    with pytest.raises(RateLimitedError):
        await provider.submit_job({"model": "x"})


@pytest.mark.asyncio
async def test_submit_job_model_not_found_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(_FakeResponse(404, text="not found")),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    with pytest.raises(ModelNotAvailableError):
        await provider.submit_job({"model": "nonexistent/model"})


@pytest.mark.asyncio
async def test_missing_api_key_never_makes_a_request(monkeypatch):
    called = {"value": False}

    def _fail(**kw):
        called["value"] = True
        return _FakeVideoAsyncClient()

    monkeypatch.setattr("app.video.providers.openrouter_video.httpx.AsyncClient", _fail)
    settings = get_settings()
    settings.openrouter_api_key = ""
    provider = OpenRouterVideoProvider(settings)
    with pytest.raises(AIProviderUnavailableError):
        await provider.submit_job({"model": "x"})
    assert called["value"] is False


@pytest.mark.asyncio
async def test_poll_job_returns_completed_status_with_urls(monkeypatch):
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(_FakeResponse(200, {
            "id": "job-abc123", "status": "completed",
            "unsigned_urls": ["https://storage.example.com/video.mp4"],
            "usage": {"cost": 0.1},
        })),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    result = await provider.poll_job("job-abc123")
    assert result.status == "completed"
    assert result.unsigned_urls == ["https://storage.example.com/video.mp4"]
    assert result.cost == 0.1


# ---------------------------------------------------------------------------
# 23. API key leakage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_never_appears_in_error_messages(monkeypatch):
    for status in (401, 403, 429, 500):
        client = _FakeVideoAsyncClient(_FakeResponse(status, text=f"Bearer {FAKE_KEY} leaked in body"))
        monkeypatch.setattr(
            "app.video.providers.openrouter_video.httpx.AsyncClient", lambda c=client, **kw: c
        )
        provider = OpenRouterVideoProvider(_settings_with_key())
        with pytest.raises(AIProviderError) as exc_info:
            await provider.submit_job({"model": "x"})
        assert FAKE_KEY not in str(exc_info.value), f"leaked at status {status}"


# ---------------------------------------------------------------------------
# QC (real ffprobe, synthetic test videos)
# ---------------------------------------------------------------------------

def _make_test_video(path: str, *, duration: float = 2.0, size: str = "320x240", with_audio: bool = False) -> None:
    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size={size}:rate=10"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    args += ["-pix_fmt", "yuv420p", path]
    subprocess.run(args, check=True, capture_output=True, timeout=30)


@pytest.mark.asyncio
async def test_qc_passes_for_valid_video_matching_expectations(tmp_path):
    video_path = str(tmp_path / "good.mp4")
    _make_test_video(video_path, duration=2.0)
    result = await run_qc(video_path, expected_duration_s=2, expected_resolution=None, expected_audio=False)
    assert result.passed is True


@pytest.mark.asyncio
async def test_qc_fails_on_duration_mismatch(tmp_path):
    video_path = str(tmp_path / "short.mp4")
    _make_test_video(video_path, duration=1.0)
    result = await run_qc(video_path, expected_duration_s=10, expected_resolution=None, expected_audio=False)
    assert result.passed is False
    assert any("Duration mismatch" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_qc_fails_on_missing_audio_when_required(tmp_path):
    video_path = str(tmp_path / "silent.mp4")
    _make_test_video(video_path, duration=1.0, with_audio=False)
    result = await run_qc(video_path, expected_duration_s=1, expected_resolution=None, expected_audio=True)
    assert result.passed is False
    assert any("Audio" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_qc_fails_on_nonexistent_file():
    result = await run_qc(
        "/tmp/does-not-exist-12345.mp4", expected_duration_s=None, expected_resolution=None, expected_audio=False
    )
    assert result.passed is False


@pytest.mark.asyncio
async def test_qc_fails_on_corrupted_file(tmp_path):
    bad_path = tmp_path / "corrupt.mp4"
    bad_path.write_bytes(b"this is not a real video file" * 100)
    result = await run_qc(str(bad_path), expected_duration_s=None, expected_resolution=None, expected_audio=False)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Job pipeline: creation, submission escalation, polling, concurrency
# ---------------------------------------------------------------------------

async def _make_user(db_session, email: str) -> User:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


async def _seed_catalog(db_session, *models: VideoModelCatalogEntry) -> None:
    for m in models:
        db_session.add(m)
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_video_job_persists_resolved_selection(db_session):
    user = await _make_user(db_session, "video-create@example.com")
    await _seed_catalog(db_session, _model("acme/a", quality=1.0), _model("acme/b", quality=0.5))

    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="a cat",
    )
    assert job.primary_model_id == "acme/a"
    assert json.loads(job.fallback_chain_json) == ["acme/b"]
    assert job.status == AIVideoJobStatus.QUEUED


@pytest.mark.asyncio
async def test_create_video_job_raises_validation_error_when_impossible(db_session):
    from app.core.errors import ValidationError

    user = await _make_user(db_session, "video-impossible@example.com")
    # Empty catalog -- nothing can possibly satisfy any request.
    with pytest.raises(ValidationError):
        await vg_service.create_video_job(
            db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
        )


class _ScriptedVideoProvider:
    """Fake OpenRouterVideoProvider: scripted submit/poll/download
    responses per call, so pipeline tests never touch the network."""

    def __init__(self, submit_results=None, poll_results=None, download_bytes=b"fake-mp4-bytes"):
        self._submit_results = list(submit_results or [])
        self._poll_results = list(poll_results or [])
        self._download_bytes = download_bytes
        self.submit_calls: list[dict] = []

    async def submit_job(self, payload):
        self.submit_calls.append(payload)
        result = self._submit_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def poll_job(self, provider_job_id):
        return self._poll_results.pop(0)

    async def download_content(self, provider_job_id, local_path, *, index=0):
        with open(local_path, "wb") as f:
            f.write(self._download_bytes)
        return len(self._download_bytes)

    async def download_from_url(self, url, local_path):
        return await self.download_content(None, local_path)


@pytest.mark.asyncio
async def test_submission_escalates_to_fallback_on_non_retryable_error(db_session, monkeypatch):
    user = await _make_user(db_session, "video-fallback@example.com")
    await _seed_catalog(db_session, _model("acme/broken"), _model("acme/works"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    assert job.selected_model_id == "acme/broken"

    fake_provider = _ScriptedVideoProvider(submit_results=[ModelNotAvailableError("gone")])
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda settings: fake_provider
    )
    await vg_service.submit_attempt(db_session, job)

    assert job.status == AIVideoJobStatus.RETRYING
    assert job.selected_model_id == "acme/works"
    assert job.fallback_used is True

    attempts = (await db_session.scalars(
        select(VideoGenerationAttempt).where(VideoGenerationAttempt.video_job_id == job.id)
    )).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "failed"


@pytest.mark.asyncio
async def test_submission_retries_same_model_on_transient_error_before_escalating(db_session, monkeypatch):
    user = await _make_user(db_session, "video-retry-same@example.com")
    await _seed_catalog(db_session, _model("acme/flaky"), _model("acme/backup"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )

    fake_provider = _ScriptedVideoProvider(submit_results=[AIProviderError("transient 500")])
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda settings: fake_provider
    )
    await vg_service.submit_attempt(db_session, job)

    # A generic AIProviderError is retryable-on-same-model -- must NOT
    # have escalated to the fallback yet.
    assert job.selected_model_id == "acme/flaky"
    assert job.status == AIVideoJobStatus.RETRYING
    assert job.next_retry_at is not None


@pytest.mark.asyncio
async def test_job_fails_cleanly_when_entire_fallback_chain_exhausted(db_session, monkeypatch):
    user = await _make_user(db_session, "video-exhausted@example.com")
    await _seed_catalog(db_session, _model("acme/only"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    assert job.max_attempts == 1

    fake_provider = _ScriptedVideoProvider(submit_results=[ModelNotAvailableError("gone")])
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda settings: fake_provider
    )
    await vg_service.submit_attempt(db_session, job)

    assert job.status == AIVideoJobStatus.FAILED
    assert job.error is not None


@pytest.mark.asyncio
async def test_poll_and_progress_completes_job_and_downloads_output(db_session, monkeypatch, tmp_path):
    settings = get_settings()
    settings.storage_local_path = str(tmp_path)
    user = await _make_user(db_session, "video-complete@example.com")
    await _seed_catalog(db_session, _model("acme/works"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x", duration=2,
    )

    submit_provider = _ScriptedVideoProvider(
        submit_results=[VideoGenerationJobResult(provider_job_id="job-1", status="pending")]
    )
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda s: submit_provider
    )
    await vg_service.submit_attempt(db_session, job, settings)
    assert job.status == AIVideoJobStatus.SUBMITTED

    real_video_path = str(tmp_path / "real_output.mp4")
    _make_test_video(real_video_path, duration=2.0)
    with open(real_video_path, "rb") as f:
        real_bytes = f.read()

    poll_provider = _ScriptedVideoProvider(
        poll_results=[VideoGenerationJobResult(
            provider_job_id="job-1", status="completed",
            unsigned_urls=[], cost=0.05,
        )],
        download_bytes=real_bytes,
    )
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda s: poll_provider
    )
    summary = await vg_service.poll_and_progress_jobs(db_session, settings)

    assert summary["completed"] == 1
    await db_session.refresh(job)
    assert job.status == AIVideoJobStatus.COMPLETED
    assert job.output_url is not None
    assert job.cost_actual == 0.05


@pytest.mark.asyncio
async def test_poll_escalates_to_fallback_when_provider_reports_failed(db_session, monkeypatch):
    user = await _make_user(db_session, "video-poll-fail@example.com")
    await _seed_catalog(db_session, _model("acme/primary"), _model("acme/secondary"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )

    submit_provider = _ScriptedVideoProvider(
        submit_results=[VideoGenerationJobResult(provider_job_id="job-1", status="pending")]
    )
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda s: submit_provider
    )
    await vg_service.submit_attempt(db_session, job)

    poll_provider = _ScriptedVideoProvider(
        poll_results=[VideoGenerationJobResult(
            provider_job_id="job-1", status="failed", error="upstream generation error"
        )]
    )
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda s: poll_provider
    )
    summary = await vg_service.poll_and_progress_jobs(db_session)

    assert summary["failed"] == 1
    await db_session.refresh(job)
    assert job.status == AIVideoJobStatus.RETRYING
    assert job.selected_model_id == "acme/secondary"
    assert job.fallback_used is True


@pytest.mark.asyncio
async def test_concurrent_jobs_progress_independently(db_session, monkeypatch):
    user = await _make_user(db_session, "video-concurrent@example.com")
    await _seed_catalog(db_session, _model("acme/only"))
    job_a = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="a",
    )
    job_b = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="b",
    )
    assert job_a.id != job_b.id

    provider = _ScriptedVideoProvider(submit_results=[
        VideoGenerationJobResult(provider_job_id="job-a", status="pending"),
        VideoGenerationJobResult(provider_job_id="job-b", status="pending"),
    ])
    monkeypatch.setattr("app.modules.video_generation.service.OpenRouterVideoProvider", lambda s: provider)
    # A single AsyncSession can't safely interleave two truly concurrent
    # transactions (that's a SQLAlchemy AsyncSession constraint, not a
    # video-pipeline one) -- in production each Celery task opens its own
    # WorkerSessionLocal(), so real concurrent jobs never share a session.
    # This still verifies what matters here: two jobs' state never
    # cross-contaminates when advanced independently.
    await vg_service.submit_attempt(db_session, job_a)
    await vg_service.submit_attempt(db_session, job_b)
    assert job_a.status == AIVideoJobStatus.SUBMITTED
    assert job_b.status == AIVideoJobStatus.SUBMITTED
    assert len(provider.submit_calls) == 2
    assert all(c["model"] == "acme/only" for c in provider.submit_calls)


# ---------------------------------------------------------------------------
# 25. New model discovery end-to-end (catalog -> router sees it immediately)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_newly_discovered_model_is_immediately_selectable(db_session, monkeypatch):
    settings = get_settings()
    settings.openrouter_api_key = FAKE_KEY
    monkeypatch.setattr(
        "app.video.catalog.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"data": [
            {"id": "brand-new/v1", "name": "Brand New V1", "generate_audio": False,
             "supported_resolutions": ["720p"]},
        ]})),
    )
    await catalog_module.refresh_catalog(db_session, settings)
    catalog = await catalog_module.list_active_models(db_session)
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO)
    selection = select_best_model(catalog, req)
    assert selection.primary_model_id == "brand-new/v1"


# ---------------------------------------------------------------------------
# ZDR / privacy guardrail detection and policy-aware routing
# ---------------------------------------------------------------------------

def _guardrail_404_response() -> _FakeResponse:
    # Exact shape live-verified against the real OpenRouter API.
    body = {
        "error": {
            "message": "0 endpoints out of 1 requested are available matching your guardrail restrictions",
            "code": 404,
            "metadata": {"ineligibility_reasons": [{"reason": "zdr-violation-by-guardrail", "endpoint_count": 1}]},
        }
    }
    return _FakeResponse(404, body, text=json.dumps(body))


@pytest.mark.asyncio
async def test_zdr_guardrail_rejection_raises_dedicated_error_not_generic_404(monkeypatch):
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(_guardrail_404_response()),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    with pytest.raises(PrivacyPolicyViolationError):
        await provider.submit_job({"model": "some/model", "prompt": "x"})


@pytest.mark.asyncio
async def test_genuine_unknown_model_404_still_raises_model_not_available(monkeypatch):
    # A plain 404 (no guardrail metadata) must NOT be misclassified as a
    # privacy violation -- the two are handled completely differently.
    monkeypatch.setattr(
        "app.video.providers.openrouter_video.httpx.AsyncClient",
        lambda **kw: _FakeVideoAsyncClient(_FakeResponse(404, {"error": {"message": "not found", "code": 404}})),
    )
    provider = OpenRouterVideoProvider(_settings_with_key())
    with pytest.raises(ModelNotAvailableError):
        await provider.submit_job({"model": "nonexistent/model", "prompt": "x"})


def test_zdr_blocked_model_is_gated_out_of_routing():
    blocked = _model("acme/blocked")
    blocked.known_zdr_blocked = True
    healthy = _model("acme/ok")
    req = VideoRequest(generation_type=VideoGenerationType.TEXT_TO_VIDEO)
    assert passes_hard_gate(blocked, req) is False
    selection = select_best_model([blocked, healthy], req)
    assert selection.primary_model_id == "acme/ok"


def test_mark_zdr_blocked_sets_flag_and_counts_as_failure():
    model = _model("acme/x")
    catalog_module.mark_zdr_blocked(model)
    assert model.known_zdr_blocked is True
    assert model.zdr_blocked_at is not None
    assert model.failure_count == 1
    assert model.consecutive_failures == 1


@pytest.mark.asyncio
async def test_submission_marks_model_zdr_blocked_and_escalates(db_session, monkeypatch):
    user = await _make_user(db_session, "video-zdr-escalate@example.com")
    await _seed_catalog(db_session, _model("acme/blocked"), _model("acme/backup"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )

    fake_provider = _ScriptedVideoProvider(submit_results=[PrivacyPolicyViolationError("blocked by guardrail")])
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda settings: fake_provider
    )
    await vg_service.submit_attempt(db_session, job)

    assert job.selected_model_id == "acme/backup"
    assert job.status == AIVideoJobStatus.RETRYING

    blocked_row = await db_session.scalar(
        select(VideoModelCatalogEntry).where(VideoModelCatalogEntry.model_id == "acme/blocked")
    )
    assert blocked_row.known_zdr_blocked is True


@pytest.mark.asyncio
async def test_job_failed_by_zdr_on_every_model_gets_clean_error_code(db_session, monkeypatch):
    user = await _make_user(db_session, "video-zdr-exhausted@example.com")
    await _seed_catalog(db_session, _model("acme/only"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    assert job.max_attempts == 1

    fake_provider = _ScriptedVideoProvider(submit_results=[PrivacyPolicyViolationError("blocked")])
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda settings: fake_provider
    )
    await vg_service.submit_attempt(db_session, job)

    assert job.status == AIVideoJobStatus.FAILED
    assert job.error_code == vg_service.ZDR_POLICY_BLOCKED_ERROR_CODE
    assert "openrouter.ai/workspaces" in job.error
    # The raw per-attempt provider text must never be the final surfaced
    # error once we know it was a uniform policy block.
    assert job.error != "blocked"


@pytest.mark.asyncio
async def test_mixed_failures_do_not_get_the_clean_zdr_code(db_session, monkeypatch):
    # If even ONE attempt failed for a different reason, don't claim it
    # was purely a privacy-policy block -- that would be misleading.
    user = await _make_user(db_session, "video-mixed-fail@example.com")
    await _seed_catalog(db_session, _model("acme/a"), _model("acme/b"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )

    fake_provider = _ScriptedVideoProvider(submit_results=[
        AIProviderUnavailableError("network blip"),
        PrivacyPolicyViolationError("blocked"),
    ])
    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda settings: fake_provider
    )
    await vg_service.submit_attempt(db_session, job)  # acme/a fails -> escalate
    await vg_service.submit_attempt(db_session, job)  # acme/b fails -> exhausted

    assert job.status == AIVideoJobStatus.FAILED
    assert job.error_code != vg_service.ZDR_POLICY_BLOCKED_ERROR_CODE


# ---------------------------------------------------------------------------
# Circuit breaker: OPEN -> HALF_OPEN cooldown recovery
# ---------------------------------------------------------------------------

def test_circuit_recovers_to_half_open_after_cooldown():
    model = _model("acme/x", circuit_state=CircuitState.OPEN)
    model.circuit_opened_at = datetime.now(UTC) - timedelta(seconds=400)
    recovered = catalog_module.recover_expired_circuits([model], cooldown_seconds=300)
    assert recovered == 1
    assert model.circuit_state == CircuitState.HALF_OPEN


def test_circuit_does_not_recover_before_cooldown_elapses():
    model = _model("acme/x", circuit_state=CircuitState.OPEN)
    model.circuit_opened_at = datetime.now(UTC) - timedelta(seconds=60)
    recovered = catalog_module.recover_expired_circuits([model], cooldown_seconds=300)
    assert recovered == 0
    assert model.circuit_state == CircuitState.OPEN


def test_half_open_probe_failure_reopens_circuit():
    model = _model("acme/x", circuit_state=CircuitState.HALF_OPEN)
    catalog_module.record_failure(model)
    assert model.circuit_state == CircuitState.OPEN


def test_half_open_probe_success_closes_circuit():
    model = _model("acme/x", circuit_state=CircuitState.HALF_OPEN)
    catalog_module.record_success(model, latency_ms=1000)
    assert model.circuit_state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_list_active_models_auto_recovers_expired_circuits(db_session):
    model = _model("acme/recoverable", circuit_state=CircuitState.OPEN)
    model.circuit_opened_at = datetime.now(UTC) - timedelta(seconds=400)
    db_session.add(model)
    await db_session.commit()

    active = await catalog_module.list_active_models(db_session)
    recovered = next(m for m in active if m.model_id == "acme/recoverable")
    assert recovered.circuit_state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# Cost / concurrency / duration limits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duration_over_configured_max_is_rejected(db_session):
    user = await _make_user(db_session, "video-duration-limit@example.com")
    await _seed_catalog(db_session, _model("acme/x", durations=list(range(1, 61))))
    settings = get_settings()
    with pytest.raises(ValidationError):
        await vg_service.create_video_job(
            db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
            duration=settings.video_max_duration_seconds + 5,
        )


@pytest.mark.asyncio
async def test_concurrent_job_limit_is_enforced(db_session):
    user = await _make_user(db_session, "video-concurrency-limit@example.com")
    await _seed_catalog(db_session, _model("acme/x"))
    settings = get_settings()
    for _ in range(settings.video_max_concurrent_jobs_per_user):
        await vg_service.create_video_job(
            db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
        )
    with pytest.raises(ValidationError):
        await vg_service.create_video_job(
            db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="one too many",
        )


@pytest.mark.asyncio
async def test_daily_cost_limit_is_enforced(db_session):
    user = await _make_user(db_session, "video-cost-limit@example.com")
    settings = get_settings()
    # A model priced well above the daily limit for a single job.
    expensive = _model("acme/expensive", pricing={"duration_seconds": settings.video_daily_cost_limit_usd + 1})
    await _seed_catalog(db_session, expensive)
    with pytest.raises(ValidationError):
        await vg_service.create_video_job(
            db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x", duration=1,
        )


@pytest.mark.asyncio
async def test_cost_estimate_is_recorded_at_job_creation(db_session):
    user = await _make_user(db_session, "video-cost-estimate@example.com")
    await _seed_catalog(db_session, _model("acme/x", pricing={"duration_seconds": "0.10"}))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x", duration=2,
    )
    assert job.cost_estimate == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Stuck-job reconciliation (section 12)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_stuck_queued_jobs_beyond_threshold(db_session):
    user = await _make_user(db_session, "video-stuck@example.com")
    await _seed_catalog(db_session, _model("acme/x"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    # Simulate this job having sat untouched (dispatch lost) well past the
    # reconciliation threshold.
    job.created_at = datetime.now(UTC) - timedelta(seconds=vg_service._STUCK_QUEUED_TIMEOUT_S + 60)
    await db_session.commit()

    stuck_ids = await vg_service.find_stuck_queued_job_ids(db_session)
    assert str(job.id) in stuck_ids


@pytest.mark.asyncio
async def test_recently_queued_job_is_not_considered_stuck(db_session):
    user = await _make_user(db_session, "video-not-stuck@example.com")
    await _seed_catalog(db_session, _model("acme/x"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    stuck_ids = await vg_service.find_stuck_queued_job_ids(db_session)
    assert str(job.id) not in stuck_ids


@pytest.mark.asyncio
async def test_persistent_poll_failure_eventually_escalates_instead_of_looping_forever(db_session, monkeypatch):
    user = await _make_user(db_session, "video-stuck-poll@example.com")
    await _seed_catalog(db_session, _model("acme/a"), _model("acme/b"))
    job = await vg_service.create_video_job(
        db_session, user.id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    job.status = AIVideoJobStatus.SUBMITTED
    job.provider_job_id = "job-stuck-1"
    job.submitted_at = datetime.now(UTC) - timedelta(seconds=vg_service._STUCK_POLL_TIMEOUT_S + 120)
    await db_session.commit()

    class _AlwaysFailingPoll:
        async def poll_job(self, provider_job_id):
            raise AIProviderUnavailableError("poll endpoint down")

    monkeypatch.setattr(
        "app.modules.video_generation.service.OpenRouterVideoProvider", lambda s: _AlwaysFailingPoll()
    )
    summary = await vg_service.poll_and_progress_jobs(db_session)
    assert summary["failed"] == 1
    await db_session.refresh(job)
    assert job.status == AIVideoJobStatus.RETRYING
    assert job.selected_model_id == "acme/b"


# ---------------------------------------------------------------------------
# New visibility endpoints (attempts, routing, capabilities, health)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capabilities_summary_reflects_only_usable_models(db_session):
    good = _model("acme/good", resolutions=["720p"], durations=[5], aspect_ratios=["16:9"], audio=True)
    blocked = _model("acme/blocked", resolutions=["4K"])
    blocked.known_zdr_blocked = True
    open_circuit = _model("acme/broken", resolutions=["1080p"], circuit_state=CircuitState.OPEN)
    summary = catalog_module.get_capabilities_summary([good, blocked, open_circuit])
    assert summary["resolutions"] == ["720p"]
    assert summary["durations"] == [5]
    assert summary["audio_capable_model_count"] == 1
    assert "TEXT_TO_VIDEO" in summary["generation_types"]


@pytest.mark.asyncio
async def test_health_summary_counts_real_rows(db_session):
    await _seed_catalog(
        db_session,
        _model("acme/a", is_free=True),
        _model("acme/b", is_active=False),
        _model("acme/c", circuit_state=CircuitState.OPEN),
    )
    summary = await catalog_module.get_health_summary(db_session)
    assert summary["total_models"] == 3
    assert summary["active_models"] == 2
    assert summary["inactive_models"] == 1
    assert summary["free_models"] == 1
    assert summary["circuit_breakers"]["open"] == 1


@pytest.mark.asyncio
async def test_jobs_attempts_endpoint_returns_ownership_checked_history(client, db_session):
    email = f"video-attempts-api-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"})
    token = register.json()["access_token"]
    user_id = uuid.UUID(register.json()["user"]["id"])

    await _seed_catalog(db_session, _model("acme/only"))
    job = await vg_service.create_video_job(
        db_session, user_id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )
    db_session.add(VideoGenerationAttempt(
        video_job_id=job.id, attempt_number=1, model_id="acme/only", outcome="failed",
        error_code="ModelNotAvailableError", error="gone",
        started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/video/jobs/{job.id}/attempts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["model_id"] == "acme/only"


@pytest.mark.asyncio
async def test_jobs_attempts_endpoint_rejects_other_users_job(client, db_session):
    owner_email = f"video-owner-{uuid.uuid4().hex[:8]}@example.com"
    attacker_email = f"video-attacker-{uuid.uuid4().hex[:8]}@example.com"
    owner_reg = await client.post(
        "/api/v1/auth/register", json={"email": owner_email, "password": "supersecurepassword1"}
    )
    attacker_reg = await client.post(
        "/api/v1/auth/register", json={"email": attacker_email, "password": "supersecurepassword1"}
    )
    owner_id = uuid.UUID(owner_reg.json()["user"]["id"])
    attacker_token = attacker_reg.json()["access_token"]

    await _seed_catalog(db_session, _model("acme/only"))
    job = await vg_service.create_video_job(
        db_session, owner_id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )

    resp = await client.get(
        f"/api/v1/video/jobs/{job.id}/attempts", headers={"Authorization": f"Bearer {attacker_token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_jobs_routing_endpoint_reflects_selection(client, db_session):
    email = f"video-routing-api-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"})
    token = register.json()["access_token"]
    user_id = uuid.UUID(register.json()["user"]["id"])

    await _seed_catalog(db_session, _model("acme/primary", quality=1.0), _model("acme/backup", quality=0.5))
    job = await vg_service.create_video_job(
        db_session, user_id, generation_type=VideoGenerationType.TEXT_TO_VIDEO, prompt="x",
    )

    resp = await client.get(f"/api/v1/video/jobs/{job.id}/routing", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["primary_model_id"] == "acme/primary"
    assert body["remaining_fallback_chain"] == ["acme/backup"]
    assert body["fallback_used"] is False


@pytest.mark.asyncio
async def test_capabilities_and_health_endpoints_are_reachable(client, db_session):
    email = f"video-caps-health-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"})
    token = register.json()["access_token"]
    await _seed_catalog(db_session, _model("acme/only", resolutions=["720p"]))

    caps_resp = await client.get("/api/v1/video/capabilities", headers={"Authorization": f"Bearer {token}"})
    health_resp = await client.get("/api/v1/video/health", headers={"Authorization": f"Bearer {token}"})
    assert caps_resp.status_code == 200, caps_resp.text
    assert health_resp.status_code == 200, health_resp.text
    assert "720p" in caps_resp.json()["resolutions"]
    assert health_resp.json()["total_models"] >= 1
