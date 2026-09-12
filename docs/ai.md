# AI Orchestration

## Architecture

`app/ai/orchestrator.py:AIOrchestrator` is the single entry point for every
AI call in the system. No module outside `app/ai/` constructs an
`AIProvider` or calls an LLM API directly.

```
service.py  →  AIOrchestrator.generate_structured(task, system_prompt,
                                                    user_prompt, schema)
                        │
                        ├─ tries primary provider (default: Ollama)
                        ├─ on failure/invalid JSON, retries with a
                        │  corrective message, up to max_retries
                        ├─ falls back to AI_FALLBACK_PROVIDER if primary
                        │  is exhausted
                        └─ raises AIOrchestratorError if everything fails
                           — the caller NEVER receives a fabricated result
```

Every call validates the model's JSON output against a Pydantic schema
before it reaches application code (see `_parse_and_validate`). Raw AI
output never reaches a database write — `hooks/schemas.py`,
`titles/schemas.py`, etc. all define a `_Generated*` schema the LLM's
output must satisfy.

## Providers

- **`OllamaProvider`** (`app/ai/providers/ollama.py`) — talks to a local
  Ollama server over its `/api/chat` endpoint. Default and preferred: free,
  no data leaves the host, always available for routine tasks.
- **`OpenAICompatProvider`** (`app/ai/providers/openai_compat.py`) — talks
  to OpenAI or any OpenAI-compatible chat-completions API (vLLM,
  together.ai, groq, etc. all share this wire format). Used when
  `AI_PRIMARY_PROVIDER=openai` or as `AI_FALLBACK_PROVIDER`.

Configure in `.env`:

```
AI_PRIMARY_PROVIDER=ollama
AI_FALLBACK_PROVIDER=openai        # optional
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-mini
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

## Cost control

Per the Growth OS token-optimization policy: local Ollama is the default
for every generation task (hooks, titles, scripts, SEO, thumbnail briefs,
Next Best Video creative direction, platform-specific distribution
copy). External AI is opt-in via `AI_FALLBACK_PROVIDER` or by setting
`AI_PRIMARY_PROVIDER=openai` explicitly — CreatorOS never calls an external
paid API by default.

## What AI does and does not control

AI generates **creative content and framing** (a hook's wording, a title
candidate, a script outline, SEO copy, a thumbnail concept, the narrative
around a recommendation). AI **never** computes an analytics number,
trend score, or opportunity score — those are deterministic functions over
real stored data (see `app/core/data_quality.py` and
`app/modules/trends/service.py`/`topics/service.py` for the scoring
formulas). This split is enforced by construction: the scoring modules
never import `app.ai`.

## Adding a new AI provider

1. Implement `AIProvider` (`app/ai/providers/base.py`) — `complete()` and
   `is_available()`.
2. Register it in `app/ai/orchestrator.py:build_orchestrator()`'s
   `providers` dict.
3. No other code changes — every existing `generate_structured()` call site
   picks it up automatically via `AI_PRIMARY_PROVIDER`/`AI_FALLBACK_PROVIDER`.

## Known limitation

Prompt-result caching (task #22 in the original spec: cache identical
transcript/topic/metadata inputs to avoid redundant AI calls) and formal
prompt versioning (task #23) are **not yet implemented** — every
`generate_structured()` call hits the configured provider fresh. This is
the most valuable near-term AI-cost optimization; see `docs/ROADMAP.md`.
