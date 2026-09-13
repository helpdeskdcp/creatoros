"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import engine

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Starlette wraps middleware in reverse add-order (last added = outermost),
    # so CORS is added LAST -- it must wrap everything, including an early
    # 429 from RateLimitMiddleware, or a rate-limited browser request would
    # fail as a CORS error instead of showing the real "too many requests".
    app.add_middleware(SecurityHeadersMiddleware, hsts_enabled=settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware, redis_url=settings.redis_url)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    _register_routers(app, settings)
    _register_observability(app)

    return app


def _register_routers(app: FastAPI, settings) -> None:
    from app.modules.analytics.router import router as analytics_router
    from app.modules.audit.router import router as audit_router
    from app.modules.auth.router import router as auth_router
    from app.modules.billing.router import router as billing_router
    from app.modules.channels.router import router as channels_router
    from app.modules.competitors.router import router as competitors_router
    from app.modules.content.router import router as content_router
    from app.modules.distribution.router import router as distribution_router
    from app.modules.experiments.router import router as experiments_router
    from app.modules.hooks.router import router as hooks_router
    from app.modules.media.router import router as media_router
    from app.modules.notifications.router import router as notifications_router
    from app.modules.publishing.router import router as publishing_router
    from app.modules.recommendations.router import router as recommendations_router
    from app.modules.research.router import router as research_router
    from app.modules.retention.router import router as retention_router
    from app.modules.scripts.router import router as scripts_router
    from app.modules.seo.router import router as seo_router
    from app.modules.settings.router import router as settings_router
    from app.modules.shorts.router import router as shorts_router
    from app.modules.thumbnails.router import router as thumbnails_router
    from app.modules.titles.router import router as titles_router
    from app.modules.topics.router import router as topics_router
    from app.modules.trends.router import router as trends_router
    from app.modules.users.router import router as users_router
    from app.modules.predictions.router import router as predictions_router
    from app.modules.video_updates.router import router as video_updates_router
    from app.modules.videos.router import router as videos_router

    prefix = settings.api_v1_prefix
    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(users_router, prefix=f"{prefix}/users", tags=["users"])
    app.include_router(channels_router, prefix=f"{prefix}/channels", tags=["channels"])
    app.include_router(videos_router, prefix=f"{prefix}/videos", tags=["videos"])
    app.include_router(
        video_updates_router, prefix=f"{prefix}/video-updates", tags=["video-updates"]
    )
    app.include_router(predictions_router, prefix=f"{prefix}/predictions", tags=["predictions"])
    app.include_router(
        competitors_router, prefix=f"{prefix}/competitors", tags=["competitors"]
    )
    app.include_router(trends_router, prefix=f"{prefix}/trends", tags=["trends"])
    app.include_router(topics_router, prefix=f"{prefix}/topics", tags=["topics"])
    app.include_router(research_router, prefix=f"{prefix}/research", tags=["research"])
    app.include_router(hooks_router, prefix=f"{prefix}/hooks", tags=["hooks"])
    app.include_router(titles_router, prefix=f"{prefix}/titles", tags=["titles"])
    app.include_router(scripts_router, prefix=f"{prefix}/scripts", tags=["scripts"])
    app.include_router(thumbnails_router, prefix=f"{prefix}/thumbnails", tags=["thumbnails"])
    app.include_router(seo_router, prefix=f"{prefix}/seo", tags=["seo"])
    app.include_router(content_router, prefix=f"{prefix}/content", tags=["content"])
    app.include_router(analytics_router, prefix=f"{prefix}/analytics", tags=["analytics"])
    app.include_router(retention_router, prefix=f"{prefix}/retention", tags=["retention"])
    app.include_router(experiments_router, prefix=f"{prefix}/experiments", tags=["experiments"])
    app.include_router(
        recommendations_router, prefix=f"{prefix}/recommendations", tags=["recommendations"]
    )
    app.include_router(
        notifications_router, prefix=f"{prefix}/notifications", tags=["notifications"]
    )
    app.include_router(audit_router, prefix=f"{prefix}/audit", tags=["audit"])
    app.include_router(media_router, prefix=f"{prefix}/media", tags=["media"])
    app.include_router(shorts_router, prefix=f"{prefix}/shorts", tags=["shorts"])
    app.include_router(publishing_router, prefix=f"{prefix}/publishing", tags=["publishing"])
    app.include_router(distribution_router, prefix=f"{prefix}/distribution", tags=["distribution"])
    app.include_router(settings_router, prefix=f"{prefix}/settings", tags=["settings"])
    app.include_router(billing_router, prefix=f"{prefix}/billing", tags=["billing"])


def _register_observability(app: FastAPI) -> None:
    @app.get("/health", tags=["observability"])
    async def health():
        """Liveness probe: process is up. Does not touch dependencies."""
        return {"status": "ok"}

    @app.get("/ready", tags=["observability"])
    async def ready():
        """Readiness probe: verifies the database is reachable."""
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("readiness_db_check_failed", error=str(exc))
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "database": db_ok}

    @app.get("/metrics", tags=["observability"], response_class=PlainTextResponse)
    async def metrics():
        """Minimal Prometheus-text metrics endpoint (no external deps)."""
        pool = engine.pool
        checked_out = pool.checkedout() if hasattr(pool, "checkedout") else 0
        lines = [
            "# HELP creatoros_db_pool_checked_out Checked-out DB connections",
            "# TYPE creatoros_db_pool_checked_out gauge",
            f"creatoros_db_pool_checked_out {checked_out}",
        ]

        from app.ai.metrics import get_metrics_summary
        from app.db.session import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                summary = await get_metrics_summary(db, since_minutes=60)
            lines += [
                "# HELP creatoros_ai_requests_total AI generation requests in the last 60m",
                "# TYPE creatoros_ai_requests_total gauge",
                f"creatoros_ai_requests_total {summary.count}",
                "# HELP creatoros_ai_failure_rate AI request failure rate in the last 60m",
                "# TYPE creatoros_ai_failure_rate gauge",
                f"creatoros_ai_failure_rate {summary.failure_rate}",
                "# HELP creatoros_ai_cache_hit_rate AI cache hit rate in the last 60m",
                "# TYPE creatoros_ai_cache_hit_rate gauge",
                f"creatoros_ai_cache_hit_rate {summary.cache_hit_rate}",
            ]
            if summary.avg_latency_ms is not None:
                lines += [
                    "# HELP creatoros_ai_latency_avg_ms Average AI request latency (ms), last 60m",
                    "# TYPE creatoros_ai_latency_avg_ms gauge",
                    f"creatoros_ai_latency_avg_ms {summary.avg_latency_ms}",
                    "# HELP creatoros_ai_latency_p95_ms P95 AI request latency (ms), last 60m",
                    "# TYPE creatoros_ai_latency_p95_ms gauge",
                    f"creatoros_ai_latency_p95_ms {summary.p95_latency_ms}",
                ]
            if summary.avg_queue_wait_ms is not None:
                lines += [
                    "# HELP creatoros_ai_queue_wait_avg_ms Average Ollama queue wait (ms), last 60m",
                    "# TYPE creatoros_ai_queue_wait_avg_ms gauge",
                    f"creatoros_ai_queue_wait_avg_ms {summary.avg_queue_wait_ms}",
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_metrics_endpoint_failed", error=str(exc))

        return "\n".join(lines) + "\n"


app = create_app()
