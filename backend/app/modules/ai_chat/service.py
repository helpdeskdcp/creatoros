"""General-purpose AI gateway endpoint's service layer.

Unlike every other AI-backed module (hooks/titles/scripts/seo/...), this one
has no structured schema to validate against and nothing to persist -- it's
a thin, authenticated pass-through to AIOrchestrator.generate_text for
ad-hoc prompts (e.g. exploring a model, or a caller that doesn't fit one of
the existing content-engine schemas). Business features that need a
specific, validated output should still go through generate_structured via
their own module, not this one.
"""
from app.ai.orchestrator import AIOrchestrator
from app.modules.ai_chat.schemas import AIChatRequest, AIChatResponse


async def chat(orchestrator: AIOrchestrator, payload: AIChatRequest) -> AIChatResponse:
    result = await orchestrator.generate_text(
        task="ai_chat_endpoint",
        system_prompt=payload.system_prompt,
        user_prompt=payload.prompt,
        provider=payload.provider,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    return AIChatResponse(
        success=True,
        provider=result.provider,
        model=result.model,
        response=result.text,
    )
