"""AI video generation infrastructure: the discovered OpenRouter
video-model catalog with live-tracked health/circuit-breaker state.

Mirrors the "one interface, swappable real implementations, nothing above
this layer imports the raw provider SDK" pattern already established for
AIProvider (app/ai) and YouTubeProvider (app/modules/channels/providers)
-- see app/video/providers/openrouter_video.py and app/video/router.py.

The user-facing VideoJob/VideoGenerationAttempt entities live in
app.modules.video_generation.models (a domain module, like
app.modules.publishing's PublishingRun/PublishingAttempt) -- this module
holds only the shared, infrastructure-level model catalog."""
import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class VideoModelCatalogEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per model OpenRouter's live GET /videos/models catalog
    reports. Populated and kept in sync ONLY by app.video.catalog -- never
    hand-maintained, since the whole point of live discovery is that a new
    OpenRouter model needs zero code changes to become usable (see
    refresh_video_model_catalog_task). `is_active=False` (not a delete)
    when a previously-seen model stops appearing in the live catalog, so
    historical VideoJob rows that reference it keep a resolvable name."""

    __tablename__ = "video_model_catalog"

    model_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw capability arrays exactly as OpenRouter reports them -- stored as
    # JSON text (not normalized tables) since they're read as whole units
    # by the router, never queried column-by-value.
    supported_resolutions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported_aspect_ratios_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported_durations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported_frame_images_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supports_audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Per OpenRouter's own API docs: "Image references are supported by
    # all providers" via input_references -- true for every model in the
    # catalog, not inferred. Kept as an explicit column (rather than an
    # assumption baked into the router) so a future catalog change that
    # narrows this is one row update away from being reflected correctly.
    supports_image_reference: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Inferred from description text (no boolean field exists in the live
    # API for this) -- see app.video.catalog._infer_text_to_video. Treated
    # as a soft signal, never a hard gate stronger than what the live
    # submission itself enforces.
    supports_text_to_video: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pricing_skus_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # A maintained, documented heuristic (app.video.catalog.QUALITY_TIERS) --
    # NOT sourced from OpenRouter, which exposes no quality metric. Exists
    # so quality-mode routing has something principled to sort on; every
    # caller-facing surface must be able to say so honestly.
    quality_tier_score: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # OpenRouter exposes no per-model "is this ZDR-compliant" field in the
    # catalog -- the ONLY way to learn this is empirically, from a real
    # submission being rejected with its workspace-guardrail error. Set to
    # True the first time that happens (see
    # app.video.providers.openrouter_video.PrivacyPolicyViolationError and
    # service._advance_to_next_model_or_fail) so future routing decisions
    # skip a known-blocked model without wasting an attempt on it. This is
    # a live, reactive record of THIS account's current guardrail
    # configuration, not a claim about the provider's actual ZDR support --
    # if the workspace guardrail changes, last_checked_at/zdr_blocked_at
    # aging plus a manual reset (or a future re-probe policy) is how it
    # would need to be cleared.
    known_zdr_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    zdr_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Health / circuit breaker (see app.video.catalog.record_success/
    # record_failure) ---
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    circuit_state: Mapped[CircuitState] = mapped_column(
        Enum(CircuitState, name="video_model_circuit_state"), default=CircuitState.CLOSED, nullable=False
    )
    circuit_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bounded ring buffer (most recent N latencies, JSON list of ints) --
    # enough for a real p95/avg without a dedicated metrics table.
    recent_latencies_ms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
