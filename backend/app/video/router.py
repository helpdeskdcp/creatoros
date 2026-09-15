"""VideoModelRouter: turns a generation request into a ranked list of
models (primary + fallback chain), never a single hard-coded choice.

Two-phase selection, deliberately never blurred together:
  1. HARD CAPABILITY GATE -- a model that cannot satisfy a required
     capability (duration/resolution/aspect ratio/frame control/audio) is
     removed from consideration entirely. This is a filter, not a score
     component: "closest match" only ever applies among models that pass
     the gate for whatever configuration is ultimately requested.
  2. SCORING -- among gate-surviving models, a weighted routing_score
     (mode-dependent weights) ranks them; the top-ranked model is primary,
     the rest (in score order) form the fallback chain.

If NOTHING passes the gate for the user's exact request, resolve_request()
searches for the closest valid configuration (degrade resolution, widen
duration to the nearest supported value, or drop audio) rather than ever
submitting a request no model can honestly fulfill.
"""
import json
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.modules.video_generation.models import VideoGenerationType, VideoPriorityMode
from app.video.models import CircuitState, VideoModelCatalogEntry

logger = get_logger("video.router")

# routing_score weight vectors per priority mode. All components are
# normalized to [0, 1] before weighting (see _score_model), so these
# weights are directly comparable/tunable in one place.
_WEIGHTS: dict[VideoPriorityMode, dict[str, float]] = {
    VideoPriorityMode.QUALITY: {
        "quality": 3.0, "resolution": 1.5, "aspect_ratio": 0.5, "duration": 0.5,
        "audio": 0.5, "reliability": 1.0, "latency": 0.2, "cost": 0.1,
    },
    VideoPriorityMode.FAST: {
        "quality": 0.5, "resolution": 0.5, "aspect_ratio": 0.5, "duration": 0.5,
        "audio": 0.3, "reliability": 1.0, "latency": 2.5, "cost": 0.3,
    },
    VideoPriorityMode.LOW_COST: {
        "quality": 0.3, "resolution": 0.5, "aspect_ratio": 0.5, "duration": 0.5,
        "audio": 0.3, "reliability": 0.8, "latency": 0.3, "cost": 2.5,
    },
    VideoPriorityMode.FREE_FIRST: {
        # Free-vs-paid is enforced as a hard pre-filter (see
        # _free_video_models / NoFreeVideoModelError in select_best_model),
        # so among the remaining candidates this is identical to LOW_COST.
        "quality": 0.3, "resolution": 0.5, "aspect_ratio": 0.5, "duration": 0.5,
        "audio": 0.3, "reliability": 0.8, "latency": 0.3, "cost": 2.5,
    },
    VideoPriorityMode.BALANCED: {
        "quality": 1.0, "resolution": 1.0, "aspect_ratio": 0.5, "duration": 0.5,
        "audio": 0.5, "reliability": 1.0, "latency": 1.0, "cost": 1.0,
    },
    VideoPriorityMode.AUTO: {
        # AUTO defaults to BALANCED's weights today -- a documented,
        # honest starting point rather than a claim of adaptive
        # intelligence this codebase doesn't implement yet (see the final
        # report's "recommended next improvements").
        "quality": 1.0, "resolution": 1.0, "aspect_ratio": 0.5, "duration": 0.5,
        "audio": 0.5, "reliability": 1.0, "latency": 1.0, "cost": 1.0,
    },
}

_RESOLUTION_ORDER = ["480p", "720p", "768p", "1080p", "1K", "2K", "4K"]


@dataclass
class VideoRequest:
    generation_type: VideoGenerationType
    duration: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    audio: bool = False
    priority_mode: VideoPriorityMode = VideoPriorityMode.AUTO
    allow_degraded_config: bool = True
    # FREE_FIRST-only: explicit, opt-in permission to use a paid model when
    # no free video model exists or none can satisfy this request. Defaults
    # to False -- FREE_FIRST must never silently spend credits (see
    # NoFreeVideoModelError). Ignored for every other priority mode, which
    # were already allowed to use paid models by definition.
    allow_paid_fallback: bool = False


@dataclass
class ResolvedSelection:
    primary_model_id: str
    fallback_chain: list[str]
    validated_params: dict
    degraded_from_request: bool
    notes: list[str] = field(default_factory=list)


class NoCompatibleModelError(Exception):
    """No active, circuit-CLOSED model can satisfy the request even after
    searching for the closest valid configuration. Distinct from an empty
    catalog (a configuration problem) vs. a genuinely unsatisfiable
    combination of requirements."""


class NoFreeVideoModelError(NoCompatibleModelError):
    """FREE_FIRST mode was requested (without allow_paid_fallback) and no
    genuinely free video-generation model -- confirmed via the live
    catalog's own pricing_skus, never inferred from free TEXT/image models
    being available -- can satisfy this request. The caller (see
    app.modules.video_generation.service.create_video_job) must surface
    this as the structured {"status": "NO_FREE_VIDEO_MODEL",
    "requires_credits": true, "paid_fallback_used": false} contract, never
    silently substitute a paid model."""


class CostVerificationRequiredError(NoCompatibleModelError):
    """The only model(s) that could otherwise satisfy this request have
    pricing_status="UNKNOWN" (see VideoModelCatalogEntry.pricing_status) --
    a provider this codebase has no queryable, confirmed price/free signal
    for (as of this writing: any NVIDIA model, since NVIDIA publishes no
    per-model machine-readable pricing the way OpenRouter's catalog
    exposes pricing_skus). Cost-unverified models are excluded from EVERY
    selection pool, not just FREE_FIRST's -- "if provider/model cost
    cannot be verified, do not automatically submit the job" applies
    regardless of priority_mode. The caller must surface this as a
    "Cost verification required" response, never silently fall through
    to a model whose price is simply unknown."""


def _loads(text: str | None) -> list:
    """Parses a stored capability-array JSON column back into a list.
    Real OpenRouter models (e.g. black-forest-labs/flux-video-edit,
    heygen/avatar-iv) report several capability fields as a genuine JSON
    `null`, which json.dumps(None) serializes to the string "null" -- a
    truthy string that json.loads() correctly parses back to Python None,
    not []. Every caller here treats "no declared constraint" as "don't
    gate on this", so None must normalize to [], never propagate as None
    and blow up a downstream `x in resolutions` check."""
    if not text:
        return []
    value = json.loads(text)
    return value if value is not None else []


def _supports_generation_type(model: VideoModelCatalogEntry, gen_type: VideoGenerationType) -> bool:
    if gen_type == VideoGenerationType.TEXT_TO_VIDEO:
        return model.supports_text_to_video
    if gen_type in (VideoGenerationType.IMAGE_TO_VIDEO, VideoGenerationType.REFERENCE_TO_VIDEO):
        # Confirmed by OpenRouter's own API docs (InputReference schema):
        # image references are honored by every provider.
        return model.supports_image_reference
    frame_images = _loads(model.supported_frame_images_json)
    if gen_type == VideoGenerationType.FIRST_FRAME:
        return "first_frame" in frame_images
    if gen_type == VideoGenerationType.LAST_FRAME:
        return "last_frame" in frame_images
    if gen_type == VideoGenerationType.FIRST_LAST_FRAME:
        return "first_frame" in frame_images and "last_frame" in frame_images
    return False


def passes_hard_gate(model: VideoModelCatalogEntry, request: VideoRequest) -> bool:
    """The capability filter -- section 6's "NEVER fallback to a model that
    does not support the requested duration/resolution/aspect
    ratio/input type/frame control/audio/other required capability"."""
    if not model.is_active:
        return False
    if model.circuit_state == CircuitState.OPEN:
        return False
    if model.known_zdr_blocked:
        # Section 7: never spend an attempt re-submitting to a model this
        # account's own OpenRouter workspace guardrail has already
        # rejected on privacy grounds -- that's wasted latency for a
        # request that cannot succeed, not a retryable condition.
        return False
    if not _supports_generation_type(model, request.generation_type):
        return False
    if request.resolution:
        resolutions = _loads(model.supported_resolutions_json)
        if resolutions and request.resolution not in resolutions:
            return False
    if request.aspect_ratio:
        ratios = _loads(model.supported_aspect_ratios_json)
        if ratios and request.aspect_ratio not in ratios:
            return False
    if request.duration:
        durations = _loads(model.supported_durations_json)
        if durations and request.duration not in durations:
            return False
    if request.audio and not model.supports_audio:
        return False
    return True


def _reliability_score(model: VideoModelCatalogEntry) -> float:
    total = model.success_count + model.failure_count
    if total == 0:
        return 0.7  # unproven model: neither penalized nor favored
    return model.success_count / total


def _latency_score(model: VideoModelCatalogEntry) -> float:
    latencies = _loads(model.recent_latencies_ms_json)
    if not latencies:
        return 0.5
    avg_ms = sum(latencies) / len(latencies)
    # Normalize: <=10s -> 1.0, >=180s -> 0.0, linear between.
    return max(0.0, min(1.0, 1.0 - (avg_ms - 10_000) / 170_000))


def p95_latency_ms(model: VideoModelCatalogEntry) -> float | None:
    latencies = sorted(_loads(model.recent_latencies_ms_json))
    if not latencies:
        return None
    idx = max(0, int(round(0.95 * (len(latencies) - 1))))
    return float(latencies[idx])


def estimate_cost(model: VideoModelCatalogEntry, request: VideoRequest) -> float:
    """A relative cost estimate for ranking purposes, not a billing
    quote -- pricing_skus shapes vary per provider (per-second, per-token,
    per-image, resolution-tiered), so this picks whichever numeric SKU
    best matches the requested resolution, falling back to the cheapest
    numeric SKU on the model. Good enough to rank "roughly cheaper than
    X"; the actual charge always comes from OpenRouter's own `usage.cost`
    on the completed job, which is what VideoJob.cost_actual stores."""
    pricing = json.loads(model.pricing_skus_json) if model.pricing_skus_json else {}
    numeric_skus = {k: float(v) for k, v in pricing.items() if _is_number(v)}
    if not numeric_skus:
        return 0.0
    duration = request.duration or 5
    resolution = (request.resolution or "").lower()
    if resolution:
        matching = {k: v for k, v in numeric_skus.items() if resolution in k.lower()}
        if matching:
            return round(min(matching.values()) * duration, 4)
    return round(min(numeric_skus.values()) * duration, 4)


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _cost_score(model: VideoModelCatalogEntry, request: VideoRequest, max_cost: float) -> float:
    if max_cost <= 0:
        return 1.0
    cost = estimate_cost(model, request)
    return max(0.0, 1.0 - cost / max_cost)


def _resolution_match_score(model: VideoModelCatalogEntry, request: VideoRequest) -> float:
    if not request.resolution:
        return 0.5
    resolutions = _loads(model.supported_resolutions_json)
    if request.resolution in resolutions:
        return 1.0
    return 0.3


def _duration_match_score(model: VideoModelCatalogEntry, request: VideoRequest) -> float:
    if not request.duration:
        return 0.5
    durations = _loads(model.supported_durations_json)
    if not durations:
        return 0.5
    if request.duration in durations:
        return 1.0
    closest = min(durations, key=lambda d: abs(d - request.duration))
    diff = abs(closest - request.duration)
    return max(0.0, 1.0 - diff / max(request.duration, 1))


def _aspect_ratio_match_score(model: VideoModelCatalogEntry, request: VideoRequest) -> float:
    if not request.aspect_ratio:
        return 0.5
    ratios = _loads(model.supported_aspect_ratios_json)
    return 1.0 if request.aspect_ratio in ratios else 0.2


def _audio_match_score(model: VideoModelCatalogEntry, request: VideoRequest) -> float:
    if not request.audio:
        return 1.0
    return 1.0 if model.supports_audio else 0.0


def score_model(
    model: VideoModelCatalogEntry, request: VideoRequest, candidates: list[VideoModelCatalogEntry]
) -> float:
    """routing_score = weighted sum of normalized [0,1] component scores.
    See module docstring for the two-phase gate-then-score design and
    _WEIGHTS for the per-priority-mode weight vectors."""
    weights = _WEIGHTS[request.priority_mode]
    max_cost = max((estimate_cost(m, request) for m in candidates), default=0.0)
    return (
        weights["quality"] * model.quality_tier_score
        + weights["resolution"] * _resolution_match_score(model, request)
        + weights["aspect_ratio"] * _aspect_ratio_match_score(model, request)
        + weights["duration"] * _duration_match_score(model, request)
        + weights["audio"] * _audio_match_score(model, request)
        + weights["reliability"] * _reliability_score(model)
        + weights["latency"] * _latency_score(model)
        + weights["cost"] * _cost_score(model, request, max_cost)
    )


def _free_video_models(candidates: list[VideoModelCatalogEntry]) -> list[VideoModelCatalogEntry]:
    """Genuinely free per the LIVE video catalog's own pricing_skus (see
    app.video.catalog._is_free: every pricing_sku is exactly 0) -- never
    inferred from OpenRouter's free TEXT/chat models existing, which is a
    completely separate catalog with no bearing on video pricing."""
    return [m for m in candidates if m.is_free]


def _closest_valid_config(
    models: list[VideoModelCatalogEntry], request: VideoRequest
) -> tuple[VideoRequest, list[str]] | None:
    """Section 6's "automatically determine the closest valid
    configuration" -- tries, in order: exact request; drop audio; degrade
    resolution one step at a time; widen to nearest supported duration
    across the whole catalog. Returns (adjusted_request, notes) for the
    first configuration at least one active model satisfies, or None."""
    notes: list[str] = []
    candidate_request = request

    def any_model_matches(req: VideoRequest) -> bool:
        return any(passes_hard_gate(m, req) for m in models)

    if any_model_matches(candidate_request):
        return candidate_request, notes

    if candidate_request.audio:
        without_audio = VideoRequest(**{**candidate_request.__dict__, "audio": False})
        if any_model_matches(without_audio):
            notes.append("Audio unavailable for the requested configuration -- disabled.")
            return without_audio, notes
        candidate_request = without_audio

    if candidate_request.resolution in _RESOLUTION_ORDER:
        start = _RESOLUTION_ORDER.index(candidate_request.resolution)
        for lower in reversed(_RESOLUTION_ORDER[:start]):
            degraded = VideoRequest(**{**candidate_request.__dict__, "resolution": lower})
            if any_model_matches(degraded):
                notes.append(f"{candidate_request.resolution} unavailable -- using {lower} instead.")
                return degraded, notes

    if candidate_request.duration:
        all_durations = sorted({d for m in models for d in _loads(m.supported_durations_json)})
        if all_durations:
            nearest = min(all_durations, key=lambda d: abs(d - candidate_request.duration))
            widened = VideoRequest(**{**candidate_request.__dict__, "duration": nearest})
            if any_model_matches(widened):
                notes.append(
                    f"{candidate_request.duration}s unavailable -- using nearest supported duration ({nearest}s)."
                )
                return widened, notes

    return None


def _no_compatible_model_message(pool: list[VideoModelCatalogEntry], request: VideoRequest) -> str:
    """A clean, specific reason instead of a generic "nothing available" --
    section 26: don't hide the actual blocker. Distinguishes "every
    capability-matching model happens to be blocked by this workspace's
    privacy policy" (an operator-actionable, external condition) from a
    genuine capability gap (no model exists that could ever satisfy this)."""

    def matches_without_zdr_check(m: VideoModelCatalogEntry) -> bool:
        saved = m.known_zdr_blocked
        m.known_zdr_blocked = False
        try:
            return passes_hard_gate(m, request)
        finally:
            m.known_zdr_blocked = saved

    would_match_but_zdr_blocked = [m for m in pool if m.known_zdr_blocked and matches_without_zdr_check(m)]
    if would_match_but_zdr_blocked:
        return (
            f"{len(would_match_but_zdr_blocked)} model(s) could otherwise satisfy this request but are "
            "blocked by this workspace's OpenRouter privacy policy (Zero Data Retention guardrail). "
            "An administrator can review this at openrouter.ai/workspaces/default/guardrails."
        )
    return "No available model can satisfy this request even with degraded parameters"


def _resolve_pool(
    pool: list[VideoModelCatalogEntry], request: VideoRequest
) -> tuple[list[VideoModelCatalogEntry], list[str], VideoRequest] | None:
    """Try to satisfy `request` using only models in `pool`. Returns
    (exact_matches, notes, effective_request) on success, or None if this
    pool -- exact or degraded -- cannot satisfy the request at all. Never
    raises: the caller decides what a failure means for *this* pool (a
    genuine dead end, vs. "try a wider pool")."""
    exact_matches = [m for m in pool if passes_hard_gate(m, request)]
    if exact_matches:
        return exact_matches, [], request
    if not request.allow_degraded_config:
        return None
    resolved = _closest_valid_config(pool, request)
    if resolved is None:
        return None
    effective_request, notes = resolved
    exact_matches = [m for m in pool if passes_hard_gate(m, effective_request)]
    if not exact_matches:
        return None
    return exact_matches, notes, effective_request


_NO_EXPLICIT_FALLBACK_PRIORITY = 2**31 - 1


def _build_selection(
    exact_matches: list[VideoModelCatalogEntry],
    notes: list[str],
    effective_request: VideoRequest,
    original_request: VideoRequest,
) -> ResolvedSelection:
    # Explicit provider-priority tiers (fallback_priority, e.g. NVIDIA=0)
    # win outright over the score; models sharing a tier -- including
    # every OpenRouter row today, which all leave fallback_priority unset
    # -- are ranked exactly as before, purely by score_model.
    def _rank_key(m: VideoModelCatalogEntry) -> tuple[int, float]:
        tier = m.fallback_priority if m.fallback_priority is not None else _NO_EXPLICIT_FALLBACK_PRIORITY
        return (tier, -score_model(m, effective_request, exact_matches))

    ranked = sorted(exact_matches, key=_rank_key)
    chain = [m.model_id for m in ranked]

    validated_params = {
        "generation_type": effective_request.generation_type.value,
        "duration": effective_request.duration,
        "resolution": effective_request.resolution,
        "aspect_ratio": effective_request.aspect_ratio,
        "audio": effective_request.audio,
    }
    logger.info(
        "video_model_selected",
        primary_model=chain[0],
        fallback_count=len(chain) - 1,
        priority_mode=original_request.priority_mode.value,
        degraded=bool(notes),
    )
    return ResolvedSelection(
        primary_model_id=chain[0],
        fallback_chain=chain[1:],
        validated_params=validated_params,
        degraded_from_request=bool(notes),
        notes=notes,
    )


def select_best_model(
    catalog: list[VideoModelCatalogEntry], request: VideoRequest
) -> ResolvedSelection:
    """The section-25 select_best_model(request) entry point. Never
    silently submits an invalid request (section 6): if the exact request
    can't be satisfied, resolves the closest valid configuration first (or
    raises NoCompatibleModelError if allow_degraded_config=False or
    nothing works at all).

    FREE_FIRST (section 8/9's hard billing guard) tries the free-only pool
    first. If that pool is empty OR can't satisfy this request's
    capabilities (even after degradation), it raises NoFreeVideoModelError
    UNLESS request.allow_paid_fallback is explicitly True, in which case --
    and only then -- it widens to the full (paid-inclusive) active pool.
    This never silently substitutes a paid model (the bug this replaces:
    the old _split_free_first() fell back to `candidates` unconditionally),
    and it never blocks a request that free models genuinely can satisfy
    just because paid ones exist too."""
    active_any_price = [m for m in catalog if m.is_active and m.circuit_state != CircuitState.OPEN]
    if not active_any_price:
        raise NoCompatibleModelError("No active video models are currently available")

    # Cost safety, applies to EVERY priority_mode (not just FREE_FIRST):
    # a model with no confirmed price/free signal is never automatically
    # eligible. See CostVerificationRequiredError.
    active = [m for m in active_any_price if m.pricing_status != "UNKNOWN"]
    cost_unverified = [m for m in active_any_price if m.pricing_status == "UNKNOWN"]

    free_first = request.priority_mode == VideoPriorityMode.FREE_FIRST
    if free_first:
        free_pool = _free_video_models(active)
        if free_pool:
            result = _resolve_pool(free_pool, request)
            if result is not None:
                exact_matches, notes, effective_request = result
                return _build_selection(exact_matches, notes, effective_request, request)
            # Free model(s) exist but none -- even degraded -- can satisfy
            # this request's specific capabilities.
            if not request.allow_paid_fallback:
                raise NoFreeVideoModelError(
                    f"{len(free_pool)} free model(s) exist but none can satisfy this request's "
                    "capabilities"
                    + ("" if request.allow_degraded_config else ", and degradation is disabled")
                    + ". Enable allow_paid_fallback to use a paid model, or add OpenRouter credits."
                )
            # else: explicit permission granted -- fall through to the full
            # pool below.
        elif not request.allow_paid_fallback:
            # Hard billing guard (section 9): FREE_FIRST + no free model at
            # all + no explicit paid-fallback permission => block before any
            # capability check even runs. Never falls through to `active`
            # (the pre-fix bug this replaces did exactly that, silently).
            raise NoFreeVideoModelError(
                "No free video-generation model is currently available on OpenRouter "
                "(checked the live catalog's own pricing, not inferred from free text models). "
                "Enable allow_paid_fallback to use a paid model, or add OpenRouter credits."
            )
        # else: allow_paid_fallback=True and no free model exists -- fall
        # through to the full (paid-inclusive) pool, explicitly permitted.

    result = _resolve_pool(active, request)
    if result is None:
        cost_blocked = [m for m in cost_unverified if passes_hard_gate(m, request)]
        if cost_blocked:
            raise CostVerificationRequiredError(
                f"{len(cost_blocked)} model(s) could satisfy this request "
                f"({', '.join(m.model_id for m in cost_blocked)}) but their pricing has not been "
                "confirmed as free or paid, so they cannot be used automatically. Verify pricing and "
                "set pricing_status explicitly before enabling them."
            )
        if not request.allow_degraded_config:
            raise NoCompatibleModelError(
                "No model supports the exact requested configuration and degradation is disabled"
            )
        raise NoCompatibleModelError(_no_compatible_model_message(active, request))
    exact_matches, notes, effective_request = result
    return _build_selection(exact_matches, notes, effective_request, request)
