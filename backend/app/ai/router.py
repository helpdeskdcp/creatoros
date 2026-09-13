"""Centralized model routing for the local Ollama provider.

CreatorOS runs on a CPU-only VPS with no GPU (see docs on Ollama tuning).
Model selection is NOT arbitrary: every default below comes from
scripts/benchmark_ollama.py's measured latency/tokens-per-second/thinking-
support results (scripts/ollama_benchmark_results.json), not a guess.
Operators can override any tier via settings without touching this file.
"""
import enum

from app.core.config import Settings


class AIMode(str, enum.Enum):
    """FAST (think=false) is the CreatorOS default for every routine
    generation/classification task -- benchmarked ~1-8s on this VPS.
    DEEP (think=true) is opt-in only, for tasks that genuinely need
    extended reasoning, and only ever routes to a thinking-capable model
    -- benchmarked ~30-65s on this VPS, 5-15x slower than FAST."""

    FAST = "fast"
    DEEP = "deep"


class ModelTier(str, enum.Enum):
    FAST_SMALL = "fast_small"
    CODING = "coding"
    DEEP = "deep"


def default_tier_for_mode(mode: AIMode) -> ModelTier:
    return ModelTier.DEEP if mode is AIMode.DEEP else ModelTier.FAST_SMALL


def resolve_ollama_model(tier: ModelTier, settings: Settings) -> str:
    """The single source of truth for "which Ollama model handles this
    tier" -- callers never hardcode a model name."""
    if tier is ModelTier.CODING:
        return settings.ollama_coding_model
    if tier is ModelTier.DEEP:
        return settings.ollama_deep_model
    return settings.ollama_model
