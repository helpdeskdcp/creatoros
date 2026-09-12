"""Shared vocabulary for the data-integrity rule that governs every analytical
endpoint in CreatorOS: never fabricate a metric, and always say how sure we are.
"""
import enum
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class DataQuality(str, enum.Enum):
    REAL = "REAL"
    ESTIMATED = "ESTIMATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Confidence(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


T = TypeVar("T")


class Metric(BaseModel, Generic[T]):
    """Wraps any computed number/value with its provenance.

    `value` is None whenever `quality` is INSUFFICIENT_DATA — callers must
    check `quality` before trusting `value`, and the API contract makes that
    explicit rather than returning a fabricated zero.
    """

    value: T | None
    quality: DataQuality
    sample_size: int
    reason: str | None = None
    source: str = "creatoros"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def insufficient_data(sample_size: int, reason: str, source: str = "creatoros") -> Metric:
    return Metric(
        value=None,
        quality=DataQuality.INSUFFICIENT_DATA,
        sample_size=sample_size,
        reason=reason,
        source=source,
    )


def real_metric(value, sample_size: int, source: str = "creatoros") -> Metric:
    return Metric(value=value, quality=DataQuality.REAL, sample_size=sample_size, source=source)


def estimated_metric(value, sample_size: int, reason: str, source: str = "creatoros") -> Metric:
    return Metric(
        value=value,
        quality=DataQuality.ESTIMATED,
        sample_size=sample_size,
        reason=reason,
        source=source,
    )


# Minimum sample sizes below which CreatorOS refuses to compute a statistic
# rather than overfitting noise. Centralized here so every module applies the
# same discipline consistently instead of picking ad hoc thresholds.
MIN_SAMPLE_SIZE_TREND = 5
MIN_SAMPLE_SIZE_RETENTION = 5
MIN_SAMPLE_SIZE_RECOMMENDATION = 10
MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK = 3
