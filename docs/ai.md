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

## Result caching (spec item #22)

`app/ai/cache.py:cached_generate()` wraps `generate_structured()` with a
database cache keyed on `(task, prompt_version, model, hash(system_prompt +
user_prompt))`, backed by the `ai_generation_cache` table. Every
AI-generation service (hooks, titles, scripts, SEO, thumbnails,
recommendations, distribution assets) calls this instead of the
orchestrator directly — an identical request never reaches the AI provider
twice. Bump the `prompt_version` argument at a call site when that
module's prompt wording changes enough that old cached results should stop
being reused (basic prompt versioning, spec item #23).

Cache writes use `db.flush()`, not `commit()` — several call sites batch
multiple generations before one commit (e.g.
`recommendations.generate_next_best_videos`), and an eager commit inside
the cache helper would break that transaction's atomicity on a mid-batch
failure.

Not yet built: a queryable AI-usage dashboard aggregating cache hit rate,
tokens, and cost per task (spec item #24) — `cached_generate()` and
`AIOrchestrator` both log structured events (`ai_cache_hit`,
`ai_cache_miss_stored`, `ai_generation_succeeded`) that such a dashboard
would aggregate; see `docs/ROADMAP.md`.
