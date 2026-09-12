"""FastAPI dependency exposing the singleton AIOrchestrator."""
from functools import lru_cache

from app.ai.orchestrator import AIOrchestrator, build_orchestrator


@lru_cache
def get_orchestrator() -> AIOrchestrator:
    return build_orchestrator()
