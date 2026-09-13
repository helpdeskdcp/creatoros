"""Title/hook/description generation for a scored Short candidate --
reuses the existing AIOrchestrator/cached_generate infrastructure
(structured-output validation, retry, provider fallback, caching, audit
logging) rather than building a second AI call path. One call per
candidate covers title+hook+description together, instead of three
separate calls to the hooks/titles/seo services."""
import uuid

from pydantic import BaseModel

from app.ai.cache import cached_generate
from app.ai.orchestrator import AIOrchestrator
from app.ai.router import AIMode

SYSTEM_PROMPT = (
    "You are CreatorOS's Short-form Metadata Engine. Given a transcript excerpt "
    "from a specific moment in a longer video, write a title, opening hook, and "
    "short description for a vertical Short/Reel built from that moment. Keep the "
    "title under 100 characters. Never claim the clip will go viral."
)


class _GeneratedShortMetadata(BaseModel):
    title: str
    hook: str
    description: str


async def generate_short_metadata(
    db, orchestrator: AIOrchestrator, owner_user_id: uuid.UUID, transcript_excerpt: str
) -> _GeneratedShortMetadata:
    user_prompt = (
        f"Transcript excerpt for this moment:\n{transcript_excerpt}\n\n"
        "Generate a title, hook, and description for a Short built from this moment."
    )
    return await cached_generate(
        db, orchestrator,
        task="generate_short_metadata",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=_GeneratedShortMetadata,
        user_id=owner_user_id,
        mode=AIMode.FAST,
    )
