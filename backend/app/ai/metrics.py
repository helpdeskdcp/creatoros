"""Safe AI observability: latency, mode, success/failure, queue wait,
token counts. Never prompt/response content, never full user identity
beyond a coarse task label -- see AIRequestMetric's docstring.

Recording a metric must never break the actual AI call it describes: any
failure here is logged and swallowed, not raised.
"""
import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIRequestMetric
from app.core.logging import get_logger

logger = get_logger("ai.metrics")


async def record_metric(
    db: AsyncSession,
    *,
    task: str,
    mode: str,
    provider: str,
    model: str,
    success: bool,
    latency_ms: int,
    cache_hit: bool = False,
    error_code: str | None = None,
    queue_wait_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    try:
        db.add(
            AIRequestMetric(
                task=task,
                mode=mode,
                provider=provider,
                model=model,
                cache_hit=cache_hit,
                success=success,
                error_code=error_code,
                latency_ms=latency_ms,
                queue_wait_ms=queue_wait_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_metric_record_failed", error=str(exc))


class AIMetricsSummary:
    def __init__(
        self,
        count: int,
        success_count: int,
        failure_rate: float,
        avg_latency_ms: float | None,
        p95_latency_ms: float | None,
        avg_queue_wait_ms: float | None,
        cache_hit_rate: float,
        by_mode: dict[str, int],
    ) -> None:
        self.count = count
        self.success_count = success_count
        self.failure_rate = failure_rate
        self.avg_latency_ms = avg_latency_ms
        self.p95_latency_ms = p95_latency_ms
        self.avg_queue_wait_ms = avg_queue_wait_ms
        self.cache_hit_rate = cache_hit_rate
        self.by_mode = by_mode


async def get_metrics_summary(db: AsyncSession, since_minutes: int = 60) -> AIMetricsSummary:
    since = datetime.now(UTC) - timedelta(minutes=since_minutes)
    rows = list(
        await db.scalars(select(AIRequestMetric).where(AIRequestMetric.created_at >= since))
    )
    count = len(rows)
    if count == 0:
        return AIMetricsSummary(0, 0, 0.0, None, None, None, 0.0, {})

    success_count = sum(1 for r in rows if r.success)
    latencies = sorted(r.latency_ms for r in rows)
    queue_waits = [r.queue_wait_ms for r in rows if r.queue_wait_ms is not None]
    cache_hits = sum(1 for r in rows if r.cache_hit)
    by_mode: dict[str, int] = {}
    for r in rows:
        by_mode[r.mode] = by_mode.get(r.mode, 0) + 1

    p95_index = min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))
    return AIMetricsSummary(
        count=count,
        success_count=success_count,
        failure_rate=round(1 - (success_count / count), 4),
        avg_latency_ms=round(statistics.mean(latencies), 1),
        p95_latency_ms=float(latencies[p95_index]),
        avg_queue_wait_ms=round(statistics.mean(queue_waits), 1) if queue_waits else None,
        cache_hit_rate=round(cache_hits / count, 4),
        by_mode=by_mode,
    )
