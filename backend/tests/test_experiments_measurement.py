"""Automated experiment measurement: pulls real metric values from
VideoMetricSnapshot/Video instead of requiring manual entry, uses a real
two-proportion z-test for proportion metrics instead of a naive
'lift > 20%' heuristic, and fixes a genuine pre-existing security gap
(record_result had no ownership check at all)."""
import uuid
from datetime import UTC, datetime

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.core.security import create_jwt
from app.modules.channels.models import Channel
from app.modules.experiments import service as experiments_service
from app.modules.experiments.measurement import measure_video_metric
from app.modules.experiments.models import ExperimentStatus
from app.modules.experiments.statistics import confidence_from_p_value, two_proportion_z_test
from app.modules.users.models import User, UserRole
from app.modules.videos.models import Video, VideoMetricSnapshot


async def _make_channel_and_video(db_session, owner_id, ctr_values: list[float]) -> uuid.UUID:
    channel = Channel(owner_user_id=owner_id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:8]}", title="T")
    db_session.add(channel)
    await db_session.flush()
    video = Video(
        channel_id=channel.id, youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}", title="Test video",
        view_count=10000,
    )
    db_session.add(video)
    await db_session.flush()
    for v in ctr_values:
        db_session.add(
            VideoMetricSnapshot(video_id=video.id, captured_at=datetime.now(UTC), estimated_ctr=v)
        )
    await db_session.commit()
    return video.id


@pytest.mark.asyncio
async def test_measure_video_metric_computes_real_average_ctr(db_session):
    user = User(email="meas1@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    video_id = await _make_channel_and_video(db_session, user.id, [0.04, 0.06, 0.05])

    result = await measure_video_metric(db_session, video_id, "ctr")

    assert result.quality == "REAL"
    assert abs(result.metric_value - 0.05) < 0.001
    assert result.sample_size == 3


@pytest.mark.asyncio
async def test_measure_video_metric_never_fabricates_when_no_data(db_session):
    user = User(email="meas2@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    video_id = await _make_channel_and_video(db_session, user.id, [])

    result = await measure_video_metric(db_session, video_id, "ctr")

    assert result.quality == "INSUFFICIENT_DATA"
    assert result.metric_value is None
    assert result.reason is not None


def test_two_proportion_z_test_detects_significant_difference():
    # Large, clearly different samples -> should be significant.
    z, p_value = two_proportion_z_test(0.08, 1000, 0.05, 1000)
    assert p_value < 0.05
    assert confidence_from_p_value(p_value) in ("HIGH", "MEDIUM")


def test_two_proportion_z_test_finds_no_significance_for_tiny_samples():
    z, p_value = two_proportion_z_test(0.06, 10, 0.05, 10)
    assert p_value > 0.05
    assert confidence_from_p_value(p_value) == "LOW"


@pytest.mark.asyncio
async def test_measure_variant_concludes_experiment_with_real_statistics(db_session):
    user = User(email="meas3@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()

    # n=200 each, rates 0.03 vs 0.10 -- computed to genuinely clear p<0.01
    # (verified: z~2.84, p~0.0045), unlike a smaller/closer sample which
    # the real z-test correctly refuses to call significant.
    control_video_id = await _make_channel_and_video(db_session, user.id, [0.03] * 200)
    winner_video_id = await _make_channel_and_video(db_session, user.id, [0.10] * 200)

    experiment = await experiments_service.create_experiment(
        db_session, user.id, "title", "Curiosity titles beat plain ones", "ctr", None, 150,
        ["Plain title", "Curiosity-driven title"],
    )
    experiment = await experiments_service.start_experiment(db_session, experiment)
    control, variant = experiment.variants

    control = await experiments_service.link_variant_video(db_session, control, control_video_id)
    variant = await experiments_service.link_variant_video(db_session, variant, winner_video_id)

    control, status_a = await experiments_service.measure_variant(db_session, control)
    assert status_a == "measured"
    variant, status_b = await experiments_service.measure_variant(db_session, variant)
    assert status_b == "measured"

    concluded = await experiments_service.get_experiment(db_session, experiment.id)
    assert concluded.status == ExperimentStatus.COMPLETED
    assert concluded.winning_variant_id == variant.id
    assert concluded.confidence in ("HIGH", "MEDIUM")  # real z-test, not the old lift heuristic


@pytest.mark.asyncio
async def test_measure_variant_without_linked_video_raises(db_session):
    user = User(email="meas4@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    experiment = await experiments_service.create_experiment(
        db_session, user.id, "title", "h", "ctr", None, 30, ["A", "B"],
    )
    control = experiment.variants[0]

    with pytest.raises(ConflictError):
        await experiments_service.measure_variant(db_session, control)


@pytest.mark.asyncio
async def test_record_result_endpoint_refuses_another_users_variant(client, db_session):
    """The pre-existing gap: record_result loaded a variant with ZERO
    ownership check. This proves the fix: get_owned_variant refuses a
    variant belonging to someone else's experiment."""
    owner = User(email="exp-owner@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(owner)
    await db_session.flush()
    experiment = await experiments_service.create_experiment(
        db_session, owner.id, "title", "h", "ctr", None, 30, ["A", "B"],
    )
    variant_id = experiment.variants[0].id

    attacker = User(email="exp-attacker@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(attacker)
    await db_session.commit()
    attacker_token, _ = create_jwt(subject=str(attacker.id), token_type="access")

    resp = await client.post(
        f"/api/v1/experiments/variants/{variant_id}/result",
        json={"sample_size": 100, "metric_value": 0.5},
        headers={"Authorization": f"Bearer {attacker_token}"},
    )

    assert resp.status_code == 404

    from app.modules.experiments.models import ExperimentVariant

    untouched = await db_session.get(ExperimentVariant, variant_id)
    assert untouched.sample_size == 0  # attacker's write never happened


@pytest.mark.asyncio
async def test_get_owned_variant_raises_not_found_for_foreign_variant(db_session):
    owner = User(email="exp-owner2@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(owner)
    await db_session.flush()
    experiment = await experiments_service.create_experiment(
        db_session, owner.id, "title", "h", "ctr", None, 30, ["A", "B"],
    )
    variant_id = experiment.variants[0].id

    other = User(email="exp-other@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(other)
    await db_session.commit()

    with pytest.raises(NotFoundError):
        await experiments_service.get_owned_variant(db_session, variant_id, other.id)
